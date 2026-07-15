"""M11 §7.4 load-test settings — a PROD-SHAPED web tier for AC-11-3, without
prod.py's deployment strictness (Sentry, real SECRET_KEY/FERNET_KEK enforcement,
secure-cookie/HSTS) that a local throwaway stack can't satisfy and that would
break decryption of already-seeded fixtures.

Inherits dev (relaxed ALLOWED_HOSTS, dev KEK so seeded data still decrypts, the
STP_LOADTEST_* env gates for RedisCache + fast MD5 hashing) and changes only what
makes the dev stack unable to load-test:

  * DEBUG = False        — the Django dev runserver + DEBUG overhead caps webhook
                           accept at ~5 rps; run this under the gunicorn `web`
                           role (SERVICE_ROLE=web) for a real 20 rps.
  * fill_ingestor route  — drain fills on the `backtest` queue (worker-backtest)
                           so a fill sweep never blocks process_alert on the
                           single order worker (the AC-11-3 queue-backlog cause).
"""
from .dev import *  # noqa: F401, F403

DEBUG = False

# Isolate the fill-drain sweep from the order-submit worker. On the default stack
# fill_ingestor shares the `celery` queue with process_alert at concurrency=1, so
# a sweep (which grows with fill backlog) starves order creation and the queue
# grows unbounded. Route it to `backtest` (drained by worker-backtest) — mirrors
# how run_broker_streams is already an isolated service.
CELERY_TASK_ROUTES = {
    **CELERY_TASK_ROUTES,  # noqa: F405 — keep run_backtest -> backtest
    "apps.orders.tasks.fill_ingestor": {"queue": "backtest"},
}
