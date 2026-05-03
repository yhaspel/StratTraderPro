"""M03 — Strategies & Webhook Config tests.

Coverage map (acceptance criteria from
``project-plan/03-strategies-and-webhook-config.md`` §4):

  AC-03-1   load_strategies idempotency                 → LoadStrategiesCommandTests
  AC-03-2   list shows system + user-uploaded badges    → StrategyListTests
  AC-03-3   3-file upload happy path                    → StrategyUploadTests
  AC-03-4   upload rejects mismatch / oversize / bad JSON → StrategyUploadValidationTests
  AC-03-5   accept-risk checkbox required               → StrategyUploadValidationTests
  AC-03-6   webhook modal returns URL + reveal-once     → WebhookConfigTests
  AC-03-7   rotation invalidates old + bumps version    → WebhookConfigRotationTests
  AC-03-8   schema validates; payload validated live    → WebhookConfigSchemaTests
  AC-03-9   copy-template + reveal-once on rotation     → WebhookConfigRotationTests
  AC-03-10  system strategies cannot be deleted         → StrategySystemImmutabilityTests
  AC-03-11  user can soft-delete their own              → StrategyDeleteTests
  AC-03-12  all endpoints require MFA                   → MFAEnforcementTests
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.strategies.models import Strategy, WebhookConfig
from apps.strategies.validators import (
    PINE_MAX_BYTES,
    StrategyValidationError,
    validate_json_schema,
    validate_payload_against_schema,
    validate_uploaded_bundle,
)
from apps.users.mfa import encrypt_secret, generate_totp_secret
from apps.users.models import MFADevice
from apps.users.services import issue_token_pair

User = get_user_model()
GOOD_PW = "SecurePass123!"
API = "/api/v1/strategies"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_user(email="trader@example.com", *, with_mfa=True):
    u = User.objects.create_user(email=email, password=GOOD_PW, display_name="Trader")
    u.is_verified = True
    u.save(update_fields=["is_verified"])
    if with_mfa:
        secret = generate_totp_secret()
        MFADevice.objects.create(
            user=u, secret_encrypted=encrypt_secret(secret), verified=True,
        )
    return u


def _auth(user) -> dict:
    pair = issue_token_pair(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {pair['access']}"}


def _valid_pine() -> bytes:
    return b"//@version=5\nstrategy('demo', overlay=true)\nplotshape(close)\n"


def _valid_desc() -> bytes:
    return b"Demo strategy. Buys on signal, sells on stop.\n"


def _valid_webhook() -> dict:
    return {
        "strategy": "demo",
        "action": "buy",
        "symbol": "AAPL",
        "qty": 1,
        "order_type": "MKT",
    }


def _bundle_files(stem="DemoStrat", *, pine=None, desc=None, webhook=None):
    """Build SimpleUploadedFile triples ready for Django test client multipart."""
    pine = pine if pine is not None else _valid_pine()
    desc = desc if desc is not None else _valid_desc()
    webhook = webhook if webhook is not None else _valid_webhook()
    if isinstance(webhook, (dict, list)):
        webhook_bytes = json.dumps(webhook).encode("utf-8")
    else:
        webhook_bytes = webhook
    return {
        "pine": SimpleUploadedFile(f"{stem}.pine", pine, content_type="text/plain"),
        "description": SimpleUploadedFile(f"{stem}_Description.txt", desc, content_type="text/plain"),
        "webhook": SimpleUploadedFile(f"{stem}_Webhook.json", webhook_bytes, content_type="application/json"),
    }


# =========================================================================
# Validators (unit-level)
# =========================================================================
class ValidatorBundleTests(TestCase):

    def test_happy_path(self):
        files = {
            "pine": ("DemoStrat.pine", _valid_pine()),
            "description": ("DemoStrat_Description.txt", _valid_desc()),
            "webhook": ("DemoStrat_Webhook.json", json.dumps(_valid_webhook()).encode()),
        }
        parsed = validate_uploaded_bundle(files)
        self.assertEqual(parsed.stem, "DemoStrat")
        self.assertEqual(parsed.webhook_template["strategy"], "demo")

    def test_pine_must_have_version_marker(self):
        files = {
            "pine": ("Bad.pine", b"strategy('no version')\n"),
            "description": ("Bad_Description.txt", _valid_desc()),
            "webhook": ("Bad_Webhook.json", json.dumps(_valid_webhook()).encode()),
        }
        with self.assertRaises(StrategyValidationError) as ctx:
            validate_uploaded_bundle(files)
        self.assertEqual(ctx.exception.code, "STRATEGY_FILE_MISMATCH")

    def test_description_filename_mismatch(self):
        files = {
            "pine": ("Foo.pine", _valid_pine()),
            "description": ("Bar_Description.txt", _valid_desc()),
            "webhook": ("Foo_Webhook.json", json.dumps(_valid_webhook()).encode()),
        }
        with self.assertRaises(StrategyValidationError) as ctx:
            validate_uploaded_bundle(files)
        self.assertEqual(ctx.exception.code, "STRATEGY_FILE_MISMATCH")

    def test_pine_too_large(self):
        files = {
            "pine": ("Big.pine", b"//@version=5\n" + b"x" * (PINE_MAX_BYTES + 1)),
            "description": ("Big_Description.txt", _valid_desc()),
            "webhook": ("Big_Webhook.json", json.dumps(_valid_webhook()).encode()),
        }
        with self.assertRaises(StrategyValidationError) as ctx:
            validate_uploaded_bundle(files)
        self.assertEqual(ctx.exception.code, "STRATEGY_FILE_TOO_LARGE")

    def test_webhook_bad_json(self):
        files = {
            "pine": ("OkayStrat.pine", _valid_pine()),
            "description": ("OkayStrat_Description.txt", _valid_desc()),
            "webhook": ("OkayStrat_Webhook.json", b"{not json"),
        }
        with self.assertRaises(StrategyValidationError) as ctx:
            validate_uploaded_bundle(files)
        self.assertEqual(ctx.exception.code, "STRATEGY_WEBHOOK_INVALID")

    def test_webhook_missing_required_keys(self):
        files = {
            "pine": ("OkayStrat.pine", _valid_pine()),
            "description": ("OkayStrat_Description.txt", _valid_desc()),
            "webhook": ("OkayStrat_Webhook.json", json.dumps({"strategy": "x"}).encode()),
        }
        with self.assertRaises(StrategyValidationError) as ctx:
            validate_uploaded_bundle(files)
        self.assertEqual(ctx.exception.code, "STRATEGY_WEBHOOK_INVALID")
        self.assertIn("missing", ctx.exception.message.lower())

    def test_filename_path_traversal_rejected(self):
        files = {
            "pine": ("../etc/passwd.pine", _valid_pine()),
            "description": ("okStrat_Description.txt", _valid_desc()),
            "webhook": ("okStrat_Webhook.json", json.dumps(_valid_webhook()).encode()),
        }
        with self.assertRaises(StrategyValidationError) as ctx:
            validate_uploaded_bundle(files)
        self.assertEqual(ctx.exception.code, "STRATEGY_FILE_MISMATCH")

    def test_filename_null_byte_rejected(self):
        files = {
            "pine": ("OkayStrat\x00.pine", _valid_pine()),
            "description": ("OkayStrat_Description.txt", _valid_desc()),
            "webhook": ("OkayStrat_Webhook.json", json.dumps(_valid_webhook()).encode()),
        }
        with self.assertRaises(StrategyValidationError):
            validate_uploaded_bundle(files)

    def test_xss_signature_in_description_rejected(self):
        files = {
            "pine": ("OkayStrat.pine", _valid_pine()),
            "description": ("OkayStrat_Description.txt", b"Hello <script>alert(1)</script>"),
            "webhook": ("OkayStrat_Webhook.json", json.dumps(_valid_webhook()).encode()),
        }
        with self.assertRaises(StrategyValidationError):
            validate_uploaded_bundle(files)

    def test_stem_regex_rejects_bad_chars(self):
        files = {
            "pine": ("Bad strat.pine", _valid_pine()),  # space
            "description": ("Bad strat_Description.txt", _valid_desc()),
            "webhook": ("Bad strat_Webhook.json", json.dumps(_valid_webhook()).encode()),
        }
        with self.assertRaises(StrategyValidationError):
            validate_uploaded_bundle(files)


class ValidatorJsonSchemaTests(TestCase):

    def test_empty_dict_is_valid(self):
        validate_json_schema({})  # no exception

    def test_invalid_schema_rejected(self):
        with self.assertRaises(StrategyValidationError) as ctx:
            validate_json_schema({"type": 123})
        self.assertEqual(ctx.exception.code, "WEBHOOK_SCHEMA_INVALID")

    def test_payload_validation_against_schema(self):
        schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}}
        validate_payload_against_schema({"x": 7}, schema)
        with self.assertRaises(StrategyValidationError):
            validate_payload_against_schema({"x": "nope"}, schema)


# =========================================================================
# AC-03-1, AC-03-10 — load_strategies seed command
# =========================================================================
class LoadStrategiesCommandTests(TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="load_strategies_test_"))
        # Strategy 1 — full bundle (pine + description + webhook)
        d1 = self.tmp / "01-demo-trend"
        d1.mkdir()
        (d1 / "demo_trend_strategy.pine").write_bytes(_valid_pine())
        (d1 / "demo-trend-strategy-description.txt").write_bytes(_valid_desc())
        (d1 / "demo_trend_Webhook.json").write_bytes(
            json.dumps(_valid_webhook()).encode()
        )
        # Strategy 2 — no webhook file (must synthesize default)
        d2 = self.tmp / "02-orb"
        d2.mkdir()
        (d2 / "orb_strategy.pine").write_bytes(_valid_pine())
        (d2 / "orb-description.txt").write_bytes(b"ORB description.\n")
        # A non-strategy folder (should be skipped)
        (self.tmp / ".hidden").mkdir()
        # A loose file at root (should be ignored)
        (self.tmp / "README.md").write_text("not a strategy")
        # An empty subfolder (no .pine — should be SKIP, not FAIL)
        (self.tmp / "03-empty").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_seeds_all_strategy_folders(self):
        call_command("load_strategies", str(self.tmp))
        strategies = Strategy.objects.filter(is_system=True, owner=None)
        self.assertEqual(strategies.count(), 2)
        slugs = sorted(s.slug for s in strategies)
        self.assertEqual(slugs, ["01-demo-trend", "02-orb"])
        # Each strategy got 3 files (pine / desc / webhook).
        for s in strategies:
            kinds = sorted(s.files.values_list("kind", flat=True))
            self.assertEqual(kinds, ["DESC", "PINE", "WEBHOOK_TEMPLATE"])

    def test_idempotent_rerun(self):
        call_command("load_strategies", str(self.tmp))
        call_command("load_strategies", str(self.tmp))
        self.assertEqual(
            Strategy.objects.filter(is_system=True, owner=None).count(), 2
        )
        # No duplicate StrategyFiles per strategy/kind.
        for s in Strategy.objects.filter(is_system=True):
            for kind in ("PINE", "DESC", "WEBHOOK_TEMPLATE"):
                self.assertEqual(s.files.filter(kind=kind).count(), 1)

    def test_dry_run_writes_nothing(self):
        call_command("load_strategies", str(self.tmp), dry_run=True)
        self.assertEqual(Strategy.objects.count(), 0)

    def test_synthesizes_webhook_template_when_missing(self):
        call_command("load_strategies", str(self.tmp))
        s = Strategy.objects.get(slug="02-orb")
        webhook = s.files.get(kind="WEBHOOK_TEMPLATE")
        body = json.loads(webhook.content.tobytes() if hasattr(webhook.content, "tobytes") else bytes(webhook.content))
        self.assertEqual(body["order_type"], "MKT")
        self.assertEqual(body["strategy"], "02-orb")


# =========================================================================
# View tests
# =========================================================================
class StrategyListTests(TestCase):
    """AC-03-2 — list view returns system + user uploads, with badge fields."""

    def test_list_returns_system_and_own(self):
        user = _create_user()
        Strategy.objects.create(slug="sys-a", name="Sys A", is_system=True, owner=None)
        Strategy.objects.create(slug="user-a", name="User A", is_system=False, owner=user)
        # Other user's strategies must NOT appear.
        other = _create_user(email="other@example.com")
        Strategy.objects.create(slug="other-a", name="Other A", is_system=False, owner=other)

        resp = self.client.get(f"{API}/", **_auth(user))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        slugs = sorted(d["slug"] for d in data)
        self.assertEqual(slugs, ["sys-a", "user-a"])
        # Type field is set for the badge.
        types = {d["slug"]: d["type"] for d in data}
        self.assertEqual(types["sys-a"], "system")
        self.assertEqual(types["user-a"], "user")

    def test_list_excludes_soft_deleted(self):
        user = _create_user()
        Strategy.objects.create(slug="off", name="Off", owner=user, is_enabled=False)
        Strategy.objects.create(slug="on", name="On", owner=user, is_enabled=True)
        resp = self.client.get(f"{API}/", **_auth(user))
        slugs = [d["slug"] for d in resp.json()["data"]]
        self.assertEqual(slugs, ["on"])


class StrategyUploadTests(TestCase):
    """AC-03-3 — happy path upload."""

    def test_upload_creates_strategy_and_files(self):
        user = _create_user()
        files = _bundle_files(stem="MyStrat")
        resp = self.client.post(
            f"{API}/",
            data={"accept_untested_risk": "true", **files},
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        body = resp.json()["data"]
        self.assertEqual(body["type"], "user")
        self.assertFalse(body["is_community_tested"])
        s = Strategy.objects.get(pk=body["id"])
        self.assertEqual(s.owner, user)
        self.assertFalse(s.is_system)
        self.assertEqual(s.files.count(), 3)


class StrategyUploadValidationTests(TestCase):
    """AC-03-4, AC-03-5 — upload rejects bad input / requires acknowledgement."""

    def test_missing_acknowledgement_rejected(self):
        user = _create_user()
        files = _bundle_files(stem="MyStrat")
        resp = self.client.post(
            f"{API}/",
            data={"accept_untested_risk": "false", **files},
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_oversize_pine_rejected_with_clear_code(self):
        user = _create_user()
        files = _bundle_files(
            stem="Big",
            pine=b"//@version=5\n" + b"x" * (PINE_MAX_BYTES + 1),
        )
        resp = self.client.post(
            f"{API}/",
            data={"accept_untested_risk": "true", **files},
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "STRATEGY_FILE_TOO_LARGE")

    def test_filename_mismatch_rejected(self):
        user = _create_user()
        files = _bundle_files(stem="MyStrat")
        # Swap the desc filename to something mismatching.
        files["description"] = SimpleUploadedFile(
            "Other_Description.txt", _valid_desc(), content_type="text/plain",
        )
        resp = self.client.post(
            f"{API}/",
            data={"accept_untested_risk": "true", **files},
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "STRATEGY_FILE_MISMATCH")


# =========================================================================
# AC-03-10, AC-03-11 — system immutability & user soft delete
# =========================================================================
class StrategySystemImmutabilityTests(TestCase):

    def test_user_cannot_delete_system_strategy(self):
        user = _create_user()
        s = Strategy.objects.create(slug="sys-a", name="Sys A", is_system=True, owner=None)
        resp = self.client.delete(f"{API}/{s.id}/", **_auth(user))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "STRATEGY_SYSTEM_IMMUTABLE")
        s.refresh_from_db()
        self.assertTrue(s.is_enabled)

    def test_user_cannot_modify_system_strategy(self):
        user = _create_user()
        s = Strategy.objects.create(slug="sys-a", name="Sys A", is_system=True, owner=None)
        resp = self.client.patch(
            f"{API}/{s.id}/",
            data=json.dumps({"name": "Renamed"}),
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 403)


class StrategyDeleteTests(TestCase):

    def test_user_can_soft_delete_own(self):
        user = _create_user()
        s = Strategy.objects.create(slug="mine", name="Mine", owner=user)
        resp = self.client.delete(f"{API}/{s.id}/", **_auth(user))
        self.assertEqual(resp.status_code, 200)
        s.refresh_from_db()
        self.assertFalse(s.is_enabled)

    def test_user_cannot_delete_other_users_strategy(self):
        user = _create_user()
        other = _create_user(email="other@example.com")
        s = Strategy.objects.create(slug="theirs", name="Theirs", owner=other)
        resp = self.client.delete(f"{API}/{s.id}/", **_auth(user))
        # Detail queryset filters them out: 404, not 403, to avoid leaking
        # existence.
        self.assertEqual(resp.status_code, 404)


# =========================================================================
# AC-03-6, AC-03-7, AC-03-8, AC-03-9 — webhook config + rotation + schema
# =========================================================================
class WebhookConfigTests(TestCase):

    def test_first_get_creates_config_and_reveals_secret(self):
        user = _create_user()
        s = Strategy.objects.create(slug="x", name="X", owner=user)
        resp = self.client.get(f"{API}/{s.id}/webhook-config/", **_auth(user))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]
        self.assertTrue(body["url"].startswith("https://"))
        self.assertIn(str(s.id), body["url"])
        self.assertTrue(body["reveal_once"])
        self.assertIsNotNone(body["secret"])
        # Subsequent GET hides the secret.
        resp2 = self.client.get(f"{API}/{s.id}/webhook-config/", **_auth(user))
        self.assertFalse(resp2.json()["data"]["reveal_once"])
        self.assertIsNone(resp2.json()["data"]["secret"])

    def test_user_isolation_on_webhook_secrets(self):
        user_a = _create_user()
        user_b = _create_user(email="b@example.com")
        s = Strategy.objects.create(slug="sys", name="Sys", is_system=True, owner=None)
        a = self.client.get(f"{API}/{s.id}/webhook-config/", **_auth(user_a)).json()["data"]
        b = self.client.get(f"{API}/{s.id}/webhook-config/", **_auth(user_b)).json()["data"]
        # Different users get DIFFERENT WebhookConfig rows for the same system
        # strategy. Each gets their own URL with their own user id.
        self.assertNotEqual(a["secret"], b["secret"])
        self.assertNotEqual(a["url"], b["url"])


class WebhookConfigRotationTests(TestCase):
    """AC-03-7 + AC-03-9 — rotation invalidates old, bumps version, reveals secret once."""

    def test_rotation_increments_version_and_returns_new_secret(self):
        user = _create_user()
        s = Strategy.objects.create(slug="x", name="X", owner=user)
        # Bootstrap config.
        first = self.client.get(f"{API}/{s.id}/webhook-config/", **_auth(user)).json()["data"]
        first_secret = first["secret"]
        self.assertEqual(first["version"], 1)
        # Rotate.
        rot = self.client.post(f"{API}/{s.id}/webhook-config/rotate/", **_auth(user))
        self.assertEqual(rot.status_code, 200)
        rotated = rot.json()["data"]
        self.assertEqual(rotated["version"], 2)
        self.assertNotEqual(rotated["secret"], first_secret)
        self.assertTrue(rotated["reveal_once"])
        # Confirm secret stored differs (decrypts to the new one).
        cfg = WebhookConfig.objects.get(user=user, strategy=s)
        from apps.strategies.services import decrypt_secret
        self.assertEqual(decrypt_secret(cfg.secret_encrypted), rotated["secret"])
        self.assertNotEqual(decrypt_secret(cfg.secret_encrypted), first_secret)


class WebhookConfigSchemaTests(TestCase):
    """AC-03-8 — schema editor + payload-template live validation."""

    def test_put_invalid_schema_rejected(self):
        user = _create_user()
        s = Strategy.objects.create(slug="x", name="X", owner=user)
        resp = self.client.put(
            f"{API}/{s.id}/webhook-config/",
            data=json.dumps({
                "json_schema": {"type": 123},  # invalid
                "payload_template": {"a": 1},
            }),
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "WEBHOOK_SCHEMA_INVALID")

    def test_put_payload_must_match_schema(self):
        user = _create_user()
        s = Strategy.objects.create(slug="x", name="X", owner=user)
        resp = self.client.put(
            f"{API}/{s.id}/webhook-config/",
            data=json.dumps({
                "json_schema": {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}},
                "payload_template": {"x": "not an int"},
            }),
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "STRATEGY_WEBHOOK_INVALID")

    def test_dry_run_validates_against_stored_schema(self):
        user = _create_user()
        s = Strategy.objects.create(slug="x", name="X", owner=user)
        # Initialize with default schema.
        self.client.get(f"{API}/{s.id}/webhook-config/", **_auth(user))
        ok_resp = self.client.post(
            f"{API}/{s.id}/webhook-config/dry-run/",
            data=json.dumps({"payload": {
                "strategy": "x", "action": "buy", "symbol": "AAPL",
                "qty": 1, "order_type": "MKT", "sig": "abc",
            }}),
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(ok_resp.status_code, 200)
        bad_resp = self.client.post(
            f"{API}/{s.id}/webhook-config/dry-run/",
            data=json.dumps({"payload": {"strategy": "x"}}),
            content_type="application/json",
            **_auth(user),
        )
        self.assertEqual(bad_resp.status_code, 400)


# =========================================================================
# AC-03-12 — MFA enforcement + feature flag
# =========================================================================
class MFAEnforcementTests(TestCase):

    def test_endpoint_requires_mfa(self):
        # User WITHOUT MFA enrolled → 403 MFA_REQUIRED on every endpoint.
        user = _create_user(with_mfa=False)
        resp = self.client.get(f"{API}/", **_auth(user))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "MFA_REQUIRED")

    def test_unauth_returns_401(self):
        resp = self.client.get(f"{API}/")
        self.assertEqual(resp.status_code, 401)


class FeatureFlagTests(TestCase):

    @override_settings(STRATEGIES_V1_ENABLED=False)
    def test_disabled_returns_503(self):
        user = _create_user()
        resp = self.client.get(f"{API}/", **_auth(user))
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"]["code"], "FEATURE_DISABLED")


# =========================================================================
# Security — secret-not-in-logs (DoD §5)
# =========================================================================
class SecretLeakTests(TestCase):

    def test_rotation_log_does_not_contain_secret(self):
        user = _create_user()
        s = Strategy.objects.create(slug="x", name="X", owner=user)
        # Boot config so we know the rotate path runs against an existing one.
        self.client.get(f"{API}/{s.id}/webhook-config/", **_auth(user))

        with self.assertLogs("apps.strategies.views", level="INFO") as cap:
            resp = self.client.post(f"{API}/{s.id}/webhook-config/rotate/", **_auth(user))
        secret = resp.json()["data"]["secret"]
        # The plaintext secret must NOT appear in any captured log line.
        for record in cap.output:
            self.assertNotIn(secret, record)
