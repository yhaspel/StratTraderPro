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
