"""PostgreSQL test settings (M10 §6.0).

Identical to ``config.settings.test`` except the database is the real Postgres
pointed at by ``DATABASE_URL`` — the CI job already provisions a
``postgres:16-alpine`` service and exports that env var. Used by the ``-m pg``
lane to exercise the append-only enforcement triggers, the advisory-lock chain
concurrency proof, the restricted-role privilege test, the data-migration chain
rebuild, and the audit-search index-usage EXPLAIN (all of which are no-ops or
undefined on SQLite).

The ``@skipUnless(connection.vendor == "postgresql")`` decorator on every
pg-marked test means running this module against SQLite (or without the service)
simply skips — no failures.
"""
import environ as _environ

# star-import skips _-prefixed names — name-import the helper explicitly.
from .base import _wrap_db_engines_for_prometheus
from .test import *  # noqa: F401, F403

_env = _environ.Env()

# Point at the CI/compose Postgres. Keep the django_prometheus engine wrapper so
# the DB-side series behave exactly as prod (which also runs Postgres).
DATABASES = _wrap_db_engines_for_prometheus(
    {
        "default": _env.db(
            "DATABASE_URL",
            default="postgres://test_user:test_pass@localhost:5432/test_db",
        ),
    }
)
