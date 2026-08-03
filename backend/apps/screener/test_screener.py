"""Screener integration tests (M16 §10.2 / §10.4 / §10.5).

Celery runs eager under the test settings, so a POST executes the whole
pipeline inline against ``FakeHttp`` fixtures — no live vendor calls in CI
(AC-16-12's fixture half).
"""
from __future__ import annotations

import json
import pathlib
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.m04_testutils import auth_headers, create_user
from apps.marketdata import keys as keysvc
from apps.marketdata.fmp import FMPClient
from apps.marketdata.models import Bar
from apps.screener.models import ScreenRun
from apps.strategies.models import Strategy, StrategyFile

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SCREENER_ROWS = json.loads((FIXTURES / "company_screener.json").read_text())
FMP_KEY = "fmp-test-key-abcd1234efgh5678"

BLOCK_VENDOR_ONLY = """[b]Strategy[/b]
[screen]
market_cap: >= 2B
sector: Technology
limit: 3
[/screen]
"""

BLOCK_DERIVED = """[b]Strategy[/b]
[screen]
market_cap: >= 2B
above_sma: 200
sma_rising: 200
near_52w_high: 25%
limit: 3
[/screen]
"""


# ---------------------------------------------------------------------------
# Injectable transport
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = [] if payload is None else payload

    def json(self):
        return self._payload


def _fmp_bars(n=270, base=100.0, step=0.5):
    """Raw FMP daily-bar shape, newest-first (as the vendor actually returns)."""
    rows = [
        {
            "date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "open": base + i * step, "high": base + i * step + 1,
            "low": base + i * step - 1, "close": base + i * step,
            "volume": 1_000_000 + i,
        }
        for i in range(n)
    ]
    return list(reversed(rows))


class _FakeHttp:
    """Routes by URL path and records what was asked for."""

    def __init__(self, *, screener_status=200, screener_rows=None,
                 bars=None, bar_status=None):
        self.screener_status = screener_status
        self.screener_rows = SCREENER_ROWS if screener_rows is None else screener_rows
        self.bars = bars if bars is not None else {}
        self.bar_status = bar_status or {}
        self.screener_calls = 0
        self.bar_calls: list[str] = []

    def get(self, url, params=None):
        params = params or {}
        if "/company-screener" in url:
            self.screener_calls += 1
            return _Resp(self.screener_status, self.screener_rows)
        if "/historical-price-eod" in url:
            symbol = (params.get("symbol") or "").upper()
            self.bar_calls.append(symbol)
            status = self.bar_status.get(symbol, 200)
            if status != 200:
                return _Resp(status, {})
            return _Resp(200, self.bars.get(symbol, _fmp_bars()))
        return _Resp(200, [])  # pragma: no cover — defensive


def patch_client(fake):
    """Patch the task's FMPClient so every run uses ``fake`` as its transport."""
    return mock.patch(
        "apps.screener.tasks.FMPClient",
        side_effect=lambda *a, **kw: FMPClient(api_key="k", http=fake),
    )


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
@override_settings(FMP_API_KEY=FMP_KEY, FRED_API_KEY="")
class ScreenerTestCase(TestCase):
    def setUp(self):
        cache.clear()  # FMP response cache + breaker state are cache-backed
        self.user = create_user("owner@example.com")
        self.strategy = Strategy.objects.create(
            owner=self.user, name="Demo", slug="demo", is_system=False,
        )
        self.desc = self._set_desc(self.strategy, BLOCK_VENDOR_ONLY)

    def _set_desc(self, strategy, text):
        import hashlib

        blob = text.encode("utf-8")
        sf, _ = StrategyFile.objects.update_or_create(
            strategy=strategy, kind=StrategyFile.Kind.DESC,
            defaults={
                "filename": "desc.txt", "sha256": hashlib.sha256(blob).hexdigest(),
                "content": blob, "size_bytes": len(blob),
            },
        )
        return sf

    def url(self, suffix="", strategy=None):
        sid = (strategy or self.strategy).id
        return f"/api/v1/strategies/{sid}/screen/{suffix}"

    def post_run(self, **kw):
        return self.client.post(self.url(), **{**auth_headers(self.user), **kw})


# ---------------------------------------------------------------------------
# AC-16-1 — criteria endpoint
# ---------------------------------------------------------------------------
class CriteriaEndpointTests(ScreenerTestCase):
    def test_valid_block_exposes_criteria_and_exact_fmp_mapping(self):
        resp = self.client.get(self.url("criteria/"), **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["block_present"])
        self.assertEqual(data["fmp_params"], {
            "marketCapMoreThan": 2_000_000_000, "sector": "Technology",
            "isActivelyTrading": True, "isEtf": False, "limit": 3,
        })
        self.assertEqual(data["derived"], {})

    def test_missing_block_is_block_present_false_not_an_error(self):
        self._set_desc(self.strategy, "just prose, no block")
        resp = self.client.get(self.url("criteria/"), **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["data"]["block_present"])

    def test_no_desc_file_at_all(self):
        self.desc.delete()
        resp = self.client.get(self.url("criteria/"), **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["data"]["block_present"])

    def test_malformed_block_is_400_with_line_numbered_details(self):
        self._set_desc(self.strategy, "[screen]\nbogus_key: 1\n[/screen]")
        resp = self.client.get(self.url("criteria/"), **auth_headers(self.user))
        self.assertEqual(resp.status_code, 400)
        err = resp.json()["error"]
        self.assertEqual(err["code"], "SCREEN_CRITERIA_INVALID")
        self.assertEqual(err["details"][0]["line"], 2)


# ---------------------------------------------------------------------------
# AC-16-2 / AC-16-5 / AC-16-6 — lifecycle
# ---------------------------------------------------------------------------
class LifecycleTests(ScreenerTestCase):
    def test_full_lifecycle_vendor_only(self):
        fake = _FakeHttp()
        with patch_client(fake):
            resp = self.post_run()
        self.assertEqual(resp.status_code, 202)
        run_id = resp.json()["data"]["run_id"]

        detail = self.client.get(self.url(f"runs/{run_id}/"), **auth_headers(self.user))
        self.assertEqual(detail.status_code, 200)
        data = detail.json()["data"]
        self.assertEqual(data["status"], "DONE")
        self.assertFalse(data["degraded"])
        self.assertEqual(len(data["results"]), 3)
        self.assertEqual(data["counts"]["vendor_matches"], 3)
        self.assertEqual(data["counts"]["returned"], 3)
        # No derived criteria -> zero per-symbol calls.
        self.assertEqual(fake.bar_calls, [])
        self.assertEqual(fake.screener_calls, 1)

    def test_exactly_one_screener_call_and_enrichment_capped_at_limit(self):
        """AC-16-5 + §10.4 — asserted via FakeHttp call counts."""
        self._set_desc(self.strategy, BLOCK_DERIVED)
        fake = _FakeHttp()
        with patch_client(fake):
            self.post_run()
        self.assertEqual(fake.screener_calls, 1)
        self.assertEqual(len(fake.bar_calls), 3)  # == limit, and == len(vendor rows)
        self.assertEqual(sorted(fake.bar_calls), ["AAPL", "MSFT", "NVDA"])

    def test_limit_caps_enrichment_below_vendor_match_count(self):
        self._set_desc(self.strategy, BLOCK_DERIVED.replace("limit: 3", "limit: 2"))
        fake = _FakeHttp()
        with patch_client(fake):
            self.post_run()
        self.assertEqual(len(fake.bar_calls), 2)
        run = ScreenRun.objects.get()
        self.assertEqual(run.counts["vendor_matches"], 3)

    def test_bars_are_upserted_into_the_shared_store(self):
        self._set_desc(self.strategy, BLOCK_DERIVED)
        with patch_client(_FakeHttp()):
            self.post_run()
        self.assertGreater(Bar.objects.filter(symbol="NVDA", tf="1d").count(), 250)

    def test_provenance_sha_recorded_and_frozen_against_later_edits(self):
        """AC-16-6 + A7 — the field is the DESC file's sha256."""
        with patch_client(_FakeHttp()):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(run.desc_sha256, self.desc.sha256)

        first_sha = run.desc_sha256
        self._set_desc(self.strategy, BLOCK_VENDOR_ONLY.replace("limit: 3", "limit: 2"))
        with patch_client(_FakeHttp()):
            self.post_run()
        run.refresh_from_db()
        self.assertEqual(run.desc_sha256, first_sha)  # past run untouched
        newest = ScreenRun.objects.order_by("-created_at").first()
        self.assertNotEqual(newest.desc_sha256, first_sha)

    def test_run_detail_includes_the_criteria_snapshot(self):
        """A7 — reproducibility must be visible, not just stored."""
        with patch_client(_FakeHttp()):
            resp = self.post_run()
        run_id = resp.json()["data"]["run_id"]
        data = self.client.get(
            self.url(f"runs/{run_id}/"), **auth_headers(self.user)
        ).json()["data"]
        self.assertIn("criteria", data)
        self.assertEqual(data["criteria"]["fmp_params"]["marketCapMoreThan"], 2_000_000_000)
        self.assertIn("desc_sha256", data)
        self.assertNotIn("criteria_sha256", data)  # A7 rename left no straggler

    def test_run_list_is_light_and_newest_first(self):
        with patch_client(_FakeHttp()):
            self.post_run()
            self.post_run()
        resp = self.client.get(self.url("runs/"), **auth_headers(self.user))
        rows = resp.json()["data"]
        self.assertEqual(len(rows), 2)
        self.assertNotIn("results", rows[0])
        self.assertGreaterEqual(rows[0]["created_at"], rows[1]["created_at"])

    def test_run_list_limit_is_clamped(self):
        resp = self.client.get(self.url("runs/?limit=999"), **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(self.url("runs/?limit=abc"), **auth_headers(self.user))
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# §10.5 reproducibility
# ---------------------------------------------------------------------------
class ReproducibilityTests(ScreenerTestCase):
    def test_identical_inputs_give_byte_identical_results_json(self):
        self._set_desc(self.strategy, BLOCK_DERIVED)
        with patch_client(_FakeHttp()):
            self.post_run()
        first = ScreenRun.objects.order_by("-created_at").first()
        payload_a = json.dumps(first.results, sort_keys=True)

        with patch_client(_FakeHttp()):
            self.post_run()
        second = ScreenRun.objects.order_by("-created_at").first()
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(json.dumps(second.results, sort_keys=True), payload_a)

    def test_vendor_row_order_does_not_change_the_ranking(self):
        self._set_desc(self.strategy, BLOCK_DERIVED)
        with patch_client(_FakeHttp()):
            self.post_run()
        forward = ScreenRun.objects.order_by("-created_at").first().results

        with patch_client(_FakeHttp(screener_rows=list(reversed(SCREENER_ROWS)))):
            self.post_run()
        reversed_run = ScreenRun.objects.order_by("-created_at").first().results
        self.assertEqual(
            json.dumps(reversed_run, sort_keys=True), json.dumps(forward, sort_keys=True),
        )


# ---------------------------------------------------------------------------
# AC-16-7 / A4 — degradation ladder
# ---------------------------------------------------------------------------
class DegradationTests(ScreenerTestCase):
    def setUp(self):
        super().setUp()
        self._set_desc(self.strategy, BLOCK_DERIVED)

    def test_rate_limit_mid_enrichment_stops_and_counts_the_remainder(self):
        # MSFT 429s; NVDA is fetched first (vendor order), AAPL never reached.
        fake = _FakeHttp(bar_status={"MSFT": 429})
        with patch_client(fake):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(run.status, "DONE")     # degrade, never 5xx
        self.assertTrue(run.degraded)
        # Raiser + unfetched remainder = MSFT + AAPL.
        self.assertEqual(run.counts["skipped_rate_limited"], 2)
        self.assertEqual(run.counts["skipped_unavailable"], 0)
        self.assertNotIn("AAPL", fake.bar_calls)  # stopped fetching

    def test_rate_limit_on_the_very_first_symbol_counts_every_candidate(self):
        """Boundary for A4's 'raiser + unfetched remainder' arithmetic: at
        index 0 that must be the whole candidate list, with nothing enriched."""
        fake = _FakeHttp(bar_status={"NVDA": 429})
        with patch_client(fake):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(run.status, "DONE")
        self.assertTrue(run.degraded)
        self.assertEqual(run.counts["skipped_rate_limited"], 3)  # == len(candidates)
        self.assertEqual(run.counts["enriched"], 0)
        self.assertEqual(run.counts["returned"], 0)
        # Stopped immediately: no OTHER symbol was fetched. (NVDA appears more
        # than once because the shared client retries a 429 three times before
        # it raises — that is the resilience stack, not the screener looping.)
        self.assertEqual(set(fake.bar_calls), {"NVDA"})

    def test_degraded_counts_never_exceed_the_candidate_count(self):
        """No double-counting: skipped + enriched + insufficient == candidates."""
        fake = _FakeHttp(bar_status={"MSFT": 404})
        with patch_client(fake):
            self.post_run()
        c = ScreenRun.objects.get().counts
        total = (
            c["enriched"] + c["insufficient_history"]
            + c["skipped_rate_limited"] + c["skipped_unavailable"]
        )
        self.assertEqual(total, 3)

    def test_outage_mid_enrichment_counts_skipped_unavailable(self):
        """A4 — FMPServerError is an outage, NOT a rate limit."""
        fake = _FakeHttp(bar_status={"MSFT": 500})
        with patch_client(fake):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(run.status, "DONE")
        self.assertTrue(run.degraded)
        self.assertEqual(run.counts["skipped_unavailable"], 2)
        self.assertEqual(run.counts["skipped_rate_limited"], 0)

    def test_per_symbol_4xx_skips_only_that_symbol_and_continues(self):
        """A4 — a bad/delisted ticker must not abort the whole enrichment."""
        fake = _FakeHttp(bar_status={"MSFT": 404})
        with patch_client(fake):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(run.status, "DONE")
        self.assertTrue(run.degraded)
        self.assertEqual(run.counts["skipped_unavailable"], 1)
        self.assertEqual(run.counts["skipped_rate_limited"], 0)
        self.assertIn("AAPL", fake.bar_calls)  # kept going past the bad symbol

    def test_insufficient_history_is_counted_not_silently_dropped(self):
        fake = _FakeHttp(bars={"AAPL": _fmp_bars(n=30)})
        with patch_client(fake):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(run.counts["insufficient_history"], 1)
        self.assertEqual(run.counts["enriched"], 2)
        self.assertFalse(run.degraded)  # a short series is not a vendor failure

    def test_screener_call_500_with_cold_cache_fails_the_run(self):
        fake = _FakeHttp(screener_status=500)
        with patch_client(fake):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(run.status, "FAILED")
        self.assertEqual(run.error_code, "FMP_UNAVAILABLE")

    def test_screener_call_429_with_cold_cache_fails_with_rate_limited(self):
        fake = _FakeHttp(screener_status=429)
        with patch_client(fake):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(run.status, "FAILED")
        self.assertEqual(run.error_code, "FMP_RATE_LIMITED")

    def test_counts_are_always_fully_populated(self):
        with patch_client(_FakeHttp()):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertEqual(sorted(run.counts), sorted([
            "vendor_matches", "enriched", "returned", "insufficient_history",
            "skipped_rate_limited", "skipped_unavailable",
        ]))

    def test_failed_run_still_reports_a_full_counts_dict(self):
        with patch_client(_FakeHttp(screener_status=500)):
            self.post_run()
        run = ScreenRun.objects.get()
        self.assertIn("skipped_unavailable", run.counts)


# ---------------------------------------------------------------------------
# AC-16-3 / AC-16-4 / AC-16-8 / AC-16-11 — the POST gate ladder
# ---------------------------------------------------------------------------
class PostLadderTests(ScreenerTestCase):
    @override_settings(FMP_API_KEY="")
    def test_no_key_anywhere_is_409_fmp_not_configured(self):
        resp = self.post_run()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "FMP_NOT_CONFIGURED")

    @override_settings(FMP_API_KEY="", FRED_API_KEY="")
    def test_ui_stored_key_alone_is_enough(self):
        """ADR-062 integration — no env var, key set through the UI."""
        keysvc.set_key("FMP", FMP_KEY)
        with patch_client(_FakeHttp()):
            resp = self.post_run()
        self.assertEqual(resp.status_code, 202)

    @override_settings(FMP_API_KEY=FMP_KEY, FRED_API_KEY="")
    def test_missing_fred_key_has_no_effect(self):
        with patch_client(_FakeHttp()):
            self.assertEqual(self.post_run().status_code, 202)

    def test_no_block_is_409_no_screen_criteria(self):
        self._set_desc(self.strategy, "prose only")
        resp = self.post_run()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "NO_SCREEN_CRITERIA")

    def test_invalid_block_is_400(self):
        self._set_desc(self.strategy, "[screen]\nbogus: 1\n[/screen]")
        resp = self.post_run()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "SCREEN_CRITERIA_INVALID")

    def test_active_run_precheck_returns_409(self):
        ScreenRun.objects.create(
            user=self.user, strategy=self.strategy, criteria={}, desc_sha256="x",
            status=ScreenRun.Status.RUNNING,
        )
        resp = self.post_run()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "SCREEN_RUN_ACTIVE")

    def test_db_constraint_rejects_a_second_active_run(self):
        """The partial unique index is the REAL guard — proven at the DB level,
        not through a mocked exception. The view's pre-check only narrows the
        race window; two interleaved POSTs both pass it."""
        from django.db import IntegrityError, transaction

        ScreenRun.objects.create(
            user=self.user, strategy=self.strategy, criteria={}, desc_sha256="x",
            status=ScreenRun.Status.QUEUED,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ScreenRun.objects.create(
                user=self.user, strategy=self.strategy, criteria={}, desc_sha256="y",
                status=ScreenRun.Status.RUNNING,
            )

    def test_constraint_is_partial_so_terminal_runs_may_pile_up(self):
        for _ in range(3):
            ScreenRun.objects.create(
                user=self.user, strategy=self.strategy, criteria={}, desc_sha256="x",
                status=ScreenRun.Status.DONE,
            )
        self.assertEqual(ScreenRun.objects.count(), 3)

    def test_integrity_error_on_create_is_mapped_to_the_same_409(self):
        """When the constraint fires inside the view, the caller sees the same
        code as the pre-check path — not a 500."""
        from django.db import IntegrityError

        with mock.patch(
            "apps.screener.views.ScreenRun.objects.create",
            side_effect=IntegrityError("duplicate key"),
        ):
            resp = self.post_run()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "SCREEN_RUN_ACTIVE")

    def test_terminal_runs_do_not_block_a_new_one(self):
        ScreenRun.objects.create(
            user=self.user, strategy=self.strategy, criteria={}, desc_sha256="x",
            status=ScreenRun.Status.DONE,
        )
        with patch_client(_FakeHttp()):
            self.assertEqual(self.post_run().status_code, 202)

    @override_settings(RATELIMIT_ENABLE=True)
    def test_eleventh_run_in_an_hour_is_429(self):
        cache.clear()
        with patch_client(_FakeHttp()):
            for _ in range(10):
                self.assertEqual(self.post_run().status_code, 202)
            resp = self.post_run()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["error"]["code"], "RATE_LIMITED")

    @override_settings(RATELIMIT_ENABLE=True)
    def test_the_throttle_is_per_user_not_one_global_bucket(self):
        """AC-16-8 says per USER. A URL-level `key="user"` decorator would run
        before DRF authenticates, keying every caller on AnonymousUser — one
        shared bucket that user A could exhaust for everyone."""
        cache.clear()
        other = create_user("second@example.com")
        other_strategy = Strategy.objects.create(
            owner=other, name="Other", slug="other-demo", is_system=False,
        )
        self._set_desc(other_strategy, BLOCK_VENDOR_ONLY)

        with patch_client(_FakeHttp()):
            for _ in range(10):
                self.assertEqual(self.post_run().status_code, 202)
            self.assertEqual(self.post_run().status_code, 429)  # user 1 exhausted
            # User 2 has spent nothing and must be unaffected.
            resp = self.client.post(
                self.url(strategy=other_strategy), **auth_headers(other),
            )
        self.assertEqual(resp.status_code, 202)

    @override_settings(RATELIMIT_ENABLE=True)
    def test_unauthenticated_posts_do_not_consume_a_users_quota(self):
        """Ten anonymous POSTs (all rejected) must not cost a real user a thing."""
        cache.clear()
        for _ in range(10):
            anon = self.client.post(self.url())
            self.assertIn(anon.status_code, (401, 403))
        with patch_client(_FakeHttp()):
            resp = self.post_run()
        self.assertEqual(resp.status_code, 202)


class StaleRunTests(ScreenerTestCase):
    """An abandoned QUEUED row must not lock the pair forever (no cancel API)."""

    def _stale_run(self, minutes=30):
        from apps.screener.views import STALE_AFTER  # noqa: F401 — documents the link

        run = ScreenRun.objects.create(
            user=self.user, strategy=self.strategy, criteria={}, desc_sha256="x",
            status=ScreenRun.Status.QUEUED,
        )
        ScreenRun.objects.filter(id=run.id).update(
            created_at=timezone.now() - timedelta(minutes=minutes)
        )
        return run

    def test_a_stale_queued_run_is_reaped_and_the_new_run_proceeds(self):
        stale = self._stale_run()
        with patch_client(_FakeHttp()):
            resp = self.post_run()
        self.assertEqual(resp.status_code, 202)
        stale.refresh_from_db()
        self.assertEqual(stale.status, "FAILED")
        self.assertEqual(stale.error_code, "SCREEN_STALE")
        self.assertIsNotNone(stale.finished_at)

    def test_a_fresh_active_run_is_NOT_reaped(self):
        fresh = self._stale_run(minutes=1)
        resp = self.post_run()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "SCREEN_RUN_ACTIVE")
        fresh.refresh_from_db()
        self.assertEqual(fresh.status, "QUEUED")

    def test_reaping_is_scoped_to_this_user_and_strategy(self):
        other = create_user("third@example.com")
        theirs = ScreenRun.objects.create(
            user=other, strategy=self.strategy, criteria={}, desc_sha256="x",
            status=ScreenRun.Status.QUEUED,
        )
        ScreenRun.objects.filter(id=theirs.id).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )
        self._stale_run()
        with patch_client(_FakeHttp()):
            self.post_run()
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, "QUEUED")  # untouched


# ---------------------------------------------------------------------------
# AC-16-11 / A3 — the flag gates EVERY endpoint with FEATURE_DISABLED
# ---------------------------------------------------------------------------
@override_settings(SCREENER_ENABLED=False)
class FlagOffTests(ScreenerTestCase):
    def test_every_endpoint_503s_with_the_house_code(self):
        run = ScreenRun.objects.create(
            user=self.user, strategy=self.strategy, criteria={}, desc_sha256="x",
            status=ScreenRun.Status.DONE,
        )
        targets = [
            ("get", self.url("criteria/")),
            ("post", self.url()),
            ("get", self.url("runs/")),
            ("get", self.url(f"runs/{run.id}/")),
        ]
        for method, url in targets:
            with self.subTest(url=url):
                resp = getattr(self.client, method)(url, **auth_headers(self.user))
                self.assertEqual(resp.status_code, 503)
                # A3: FEATURE_DISABLED, not SCREENER_DISABLED.
                self.assertEqual(resp.json()["error"]["code"], "FEATURE_DISABLED")

    def test_no_run_is_created_while_disabled(self):
        self.post_run()
        self.assertEqual(ScreenRun.objects.count(), 0)


# ---------------------------------------------------------------------------
# AC-16-9 — permissions
# ---------------------------------------------------------------------------
class PermissionTests(ScreenerTestCase):
    def test_unauthenticated_is_401(self):
        self.assertIn(self.client.get(self.url("criteria/")).status_code, (401, 403))

    def test_non_owner_private_strategy_is_404_not_403(self):
        other = create_user("other@example.com")
        resp = self.client.get(self.url("criteria/"), **auth_headers(other))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "STRATEGY_NOT_FOUND")

    def test_soft_deleted_strategy_is_404(self):
        from django.utils import timezone

        self.strategy.deleted_at = timezone.now()
        self.strategy.save(update_fields=["deleted_at"])
        resp = self.client.get(self.url("criteria/"), **auth_headers(self.user))
        self.assertEqual(resp.status_code, 404)

    def test_system_strategy_is_screenable_by_any_mfa_user(self):
        system = Strategy.objects.create(
            owner=None, name="Sys", slug="sys", is_system=True,
        )
        self._set_desc(system, BLOCK_VENDOR_ONLY)
        other = create_user("other2@example.com")
        resp = self.client.get(
            self.url("criteria/", strategy=system), **auth_headers(other),
        )
        self.assertEqual(resp.status_code, 200)

    def test_runs_are_strictly_owner_scoped(self):
        system = Strategy.objects.create(
            owner=None, name="Sys2", slug="sys2", is_system=True,
        )
        self._set_desc(system, BLOCK_VENDOR_ONLY)
        other = create_user("other3@example.com")
        run = ScreenRun.objects.create(
            user=self.user, strategy=system, criteria={}, desc_sha256="x",
            status=ScreenRun.Status.DONE,
        )
        # `other` can see the system strategy, but never this user's run.
        detail = self.client.get(
            self.url(f"runs/{run.id}/", strategy=system), **auth_headers(other),
        )
        self.assertEqual(detail.status_code, 404)
        listing = self.client.get(
            self.url("runs/", strategy=system), **auth_headers(other),
        )
        self.assertEqual(listing.json()["data"], [])


# ---------------------------------------------------------------------------
# §11 — audit + key-leak surfaces
# ---------------------------------------------------------------------------
class AuditAndLeakTests(ScreenerTestCase):
    def test_run_creation_is_audited_without_criteria_payload(self):
        with patch_client(_FakeHttp()):
            resp = self.post_run()
        row = AuditLog.objects.filter(event_type="screener.run_requested").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.entity_type, "strategy")
        self.assertEqual(row.entity_id, str(self.strategy.id))
        self.assertEqual(row.data_after, {"run_id": resp.json()["data"]["run_id"]})

    def test_the_fmp_key_never_reaches_a_run_row_or_the_audit_log(self):
        with patch_client(_FakeHttp()):
            self.post_run()
        run = ScreenRun.objects.get()
        blob = json.dumps({
            "criteria": run.criteria, "results": run.results, "counts": run.counts,
            "error_code": run.error_code, "task": run.celery_task_id,
        })
        self.assertNotIn(FMP_KEY, blob)
        for row in AuditLog.objects.all():
            self.assertNotIn(FMP_KEY, json.dumps(row.data_after or {}))

    def test_task_argument_is_the_run_id_only(self):
        with mock.patch("apps.screener.views.run_screen") as task:
            self.post_run()
        args, kwargs = task.delay.call_args
        self.assertEqual(kwargs, {})
        self.assertEqual(len(args), 1)
        self.assertEqual(args[0], str(ScreenRun.objects.get().id))


# ---------------------------------------------------------------------------
# §6.3 retention
# ---------------------------------------------------------------------------
class RetentionTests(ScreenerTestCase):
    def test_history_is_pruned_to_the_newest_20(self):
        from apps.screener.models import HISTORY_KEEP

        for _ in range(HISTORY_KEEP + 3):
            ScreenRun.objects.create(
                user=self.user, strategy=self.strategy, criteria={}, desc_sha256="x",
                status=ScreenRun.Status.DONE,
            )
        with patch_client(_FakeHttp()):
            self.post_run()
        self.assertEqual(
            ScreenRun.objects.filter(user=self.user, strategy=self.strategy).count(),
            HISTORY_KEEP,
        )


# ---------------------------------------------------------------------------
# Task-level edge cases
# ---------------------------------------------------------------------------
class TaskTests(ScreenerTestCase):
    def test_key_removed_between_enqueue_and_execution_fails_the_run(self):
        from apps.screener.tasks import run_screen

        run = ScreenRun.objects.create(
            user=self.user, strategy=self.strategy,
            criteria={"criteria": {}, "fmp_params": {}, "derived": {}, "limit": 3},
            desc_sha256="x",
        )
        with override_settings(FMP_API_KEY="", FRED_API_KEY=""):
            run_screen(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, "FAILED")
        self.assertEqual(run.error_code, "FMP_NOT_CONFIGURED")

    def test_missing_run_id_is_a_noop_not_a_crash(self):
        from apps.screener.tasks import run_screen

        run_screen("11111111-1111-1111-1111-111111111111")

    def test_task_declares_its_own_time_limits(self):
        """The 30s global default would SIGKILL a 50-candidate enrichment."""
        from apps.screener.tasks import run_screen

        self.assertEqual(run_screen.soft_time_limit, 240)
        self.assertEqual(run_screen.time_limit, 300)
