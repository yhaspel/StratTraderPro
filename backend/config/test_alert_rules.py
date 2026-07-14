"""Alert-rule ↔ metric-name cross-check (AC-10-9 / §10.1).

Every PromQL series referenced by infra/grafana/alerts/*.yaml must resolve to a
metric name the codebase exports (scanned from every apps/*/metrics.py) or a
known externally-produced series (django_prometheus + postgres/redis exporters).
A renamed or removed metric fails this test.
"""
import re
from pathlib import Path

import yaml
from django.test import SimpleTestCase

_REPO = Path(__file__).resolve().parents[2]
_ALERTS_DIR = _REPO / "infra" / "grafana" / "alerts"
_BACKEND = _REPO / "backend"

# PromQL functions/keywords that look like identifiers but are not metrics.
_PROMQL_TOKENS = {
    "rate", "irate", "increase", "delta", "deriv", "sum", "avg", "min", "max",
    "count", "count_values", "stddev", "stdvar", "quantile", "histogram_quantile",
    "by", "without", "on", "ignoring", "group_left", "group_right", "le", "offset",
    "bool", "clamp_max", "clamp_min", "topk", "bottomk", "absent", "abs", "ceil",
    "floor", "round", "vector", "scalar", "time", "changes", "resets", "predict_linear",
}

# Externally-produced series (not defined in our metrics.py modules).
_EXTERNAL = {
    "up",
    "django_http_responses_total_by_status_total",
    "django_http_requests_latency_seconds_by_view_method",
    "pg_stat_activity_count",
    "pg_settings_max_connections",
    "pg_up",
    "redis_up",
    "redis_connected_clients",
    # BUG-005 — usage-alerts.yaml queries the `grafanacloud-usage` datasource,
    # which Grafana Cloud maintains about our own account. These series are not
    # scraped from us and will never appear in an apps/*/metrics.py.
    "grafanacloud_instance_samples_per_second",
    "grafanacloud_org_metrics_included_series",
    # Kept allowlisted but deliberately NOT alerted on: it is a billing-period
    # aggregate that keeps climbing after the cause is fixed. See usage-alerts.yaml.
    "grafanacloud_org_metrics_billable_series",
}

_HIST_SUFFIXES = ("_bucket", "_sum", "_count")


def _exported_metric_names() -> set[str]:
    names: set[str] = set()
    pattern = re.compile(r"""(?:Counter|Gauge|Histogram|Summary)\(\s*["']([a-zA-Z_:][a-zA-Z0-9_:]*)["']""")
    for path in _BACKEND.glob("apps/*/metrics.py"):
        names |= set(pattern.findall(path.read_text()))
    return names


def _exprs_from_alerts() -> list[str]:
    exprs: list[str] = []
    for path in sorted(_ALERTS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        for group in (doc or {}).get("groups", []):
            for rule in group.get("rules", []):
                if "expr" in rule:
                    exprs.append(rule["expr"])
    return exprs


def _metric_candidates(expr: str) -> set[str]:
    e = re.sub(r'"[^"]*"', "", expr)          # strip string literals
    # grouping modifiers take LABEL names, not metrics: by(env)/without(...)/
    # on(...)/ignoring(...)/group_left(...)/group_right(...). Strip their arg
    # lists so labels like `env` aren't mistaken for unexported series.
    e = re.sub(
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", " ", e
    )
    e = re.sub(r"\{[^}]*\}", "", e)            # strip label matchers
    e = re.sub(r"\[[^\]]*\]", "", e)           # strip range selectors
    e = re.sub(r"\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b", " ", e)  # strip numeric literals (incl. 5e9)
    funcs = set(re.findall(r"([a-zA-Z_:][a-zA-Z0-9_:]*)\s*\(", e))
    idents = set(re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", e))
    return {i for i in idents if i not in funcs and i not in _PROMQL_TOKENS and not i.isdigit()}


def _normalize(name: str) -> str:
    for suf in _HIST_SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


class AlertRuleCrossCheckTests(SimpleTestCase):
    def test_alerts_dir_present(self):
        self.assertTrue(_ALERTS_DIR.is_dir(), "infra/grafana/alerts/ missing")
        self.assertTrue(list(_ALERTS_DIR.glob("*.yaml")), "no alert YAML files")

    def test_every_referenced_series_is_exported(self):
        exported = _exported_metric_names()
        self.assertIn("audit_integrity_check_total", exported)  # sanity: scan worked
        self.assertIn("celery_queue_depth", exported)
        self.assertIn("sentiment_queue_oldest_age_minutes", exported)

        known = exported | _EXTERNAL
        missing = []
        for expr in _exprs_from_alerts():
            for metric in _metric_candidates(expr):
                if metric not in known and _normalize(metric) not in known:
                    missing.append(metric)
        self.assertFalse(
            missing,
            f"alert rules reference unexported metric series: {sorted(set(missing))}",
        )


def _rules_from_alerts() -> list[dict]:
    rules: list[dict] = []
    for path in sorted(_ALERTS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        for group in (doc or {}).get("groups", []):
            rules.extend(group.get("rules", []))
    return rules


class DeadMansSwitchTests(SimpleTestCase):
    """BUG-008 — something must fire when the metrics pipeline goes silent.

    Almost every rule here embeds its comparison in the PromQL (`... > 0`), so a
    healthy system yields an empty result, which Grafana reports as Normal. That
    is correct per-rule but makes silence ambiguous: "condition false" and
    "nothing is being scraped" look identical. Without a rule that fires on
    ABSENCE, killing the agent turns the whole board green and pages nobody —
    including the kill-switch and audit-integrity alerts.

    These tests fail if that safety net is ever removed.
    """

    def test_a_rule_fires_on_absence_of_metrics(self):
        absent_rules = [
            r for r in _rules_from_alerts() if "absent(" in r.get("expr", "")
        ]
        self.assertTrue(
            absent_rules,
            "No alert rule uses absent(): nothing would fire if the Grafana Agent "
            "stopped scraping. Every self-filtering rule would return empty and be "
            "reported as Normal — alerting would be blind, not green (BUG-008).",
        )
        for rule in absent_rules:
            self.assertEqual(
                rule.get("labels", {}).get("severity"),
                "critical",
                f"{rule.get('alert')} is the dead-man's switch; it must be critical.",
            )

    def test_a_rule_fires_on_target_down(self):
        exprs = [r.get("expr", "") for r in _rules_from_alerts()]
        self.assertTrue(
            any(re.search(r"\bup\b\s*==\s*0", e) for e in exprs),
            "No `up == 0` rule: an individual scrape target could die unnoticed "
            "while the agent keeps reporting for everything else (BUG-008).",
        )


class ScrapeIntervalBudgetTests(SimpleTestCase):
    """BUG-005 — the scrape interval is a BILLING lever, not just a fidelity one.

    Grafana Cloud bills `active_series x (actual_DPM / included_DPM)` and the free
    tier includes 1 DPM. A 30s scrape is 2 DPM, so it doubles billable series and
    blows the allowance with no change in series count. Alert groups evaluate at
    1m, so a sub-60s scrape buys nothing anyway.
    """

    def test_agent_scrape_interval_is_at_least_60s(self):
        agent = _REPO / "infra" / "grafana-agent" / "agent.yaml"
        self.assertTrue(agent.is_file(), "infra/grafana-agent/agent.yaml missing")

        match = re.search(r"^\s*scrape_interval:\s*(\d+)s\s*$", agent.read_text(), re.M)
        self.assertIsNotNone(match, "agent.yaml does not set a global scrape_interval")
        self.assertGreaterEqual(
            int(match.group(1)),
            60,
            "scrape_interval < 60s doubles (or worse) Grafana Cloud billable series "
            "for zero benefit — every alert group evaluates at 1m. This is what put "
            "the account over its free-tier allowance (BUG-005).",
        )
