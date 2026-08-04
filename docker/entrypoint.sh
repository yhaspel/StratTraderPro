#!/bin/sh
# ---------------------------------------------------------------------------
# StratTraderPro backend-image entrypoint — SERVICE_ROLE dispatcher (M11 §7.0).
#
# WHY THIS EXISTS (BUG-011, S1/P0): a blank Railway "Custom Start Command" makes
# a service run the image's default CMD, which used to be `migrate && gunicorn`.
# For two months `celery-worker` and `celery-beat` ran a *second web server* in
# both environments — the default Celery queue had no consumer and beat never
# fired a single scheduled task, including `daily_loss_watcher` (a risk control).
# The service did not fail; it succeeded at being the wrong thing.
#
# The fix is not to version-control the value — it is to REMOVE THE DEFAULT.
# `SERVICE_ROLE` is required. Unset or unrecognised => exit 1 with a loud
# message and NO fallback to `web` (or to anything). A crashed deploy is visible
# in thirty seconds; a worker that is secretly gunicorn went unnoticed for two
# months. Do not "helpfully" add a default — the default is the bug.
#
# Testability without docker-in-docker: STP_ENTRYPOINT_DRY_RUN=1 prints the
# resolved command *template, un-expanded* (literal ${PORT}) and exits 0, so
# AC-11-14 is an ordinary subprocess test that compares strings against the
# pinned literals in docker/entrypoint.expected.
# ---------------------------------------------------------------------------
set -eu

VALID_ROLES="web web-dev worker worker-backtest beat streams ws"

role="${SERVICE_ROLE:-}"

fail() {
    echo "entrypoint: FATAL: $1" >&2
    echo "entrypoint: set SERVICE_ROLE to one of: ${VALID_ROLES}" >&2
    echo "entrypoint: (a blank or wrong value must NOT silently become a web server — see BUG-011)" >&2
    exit 1
}

if [ -z "${role}" ]; then
    fail "SERVICE_ROLE is unset. Refusing to guess a role."
fi

# Each command's source is pinned in docker/entrypoint.expected. Commands are
# stored as single-quoted literals so ${PORT} stays UN-expanded for the dry-run
# print; the real launch below re-expands them via `sh -c`.
case "${role}" in
    web)
        # Source: docker/backend.Dockerfile CMD. The two --access/--error-logfile
        # flags are load-bearing — dropping them silences the web tier's logs.
        cmd='python manage.py migrate --noinput && exec gunicorn config.wsgi:application --config /app/gunicorn.conf.py --bind 0.0.0.0:${PORT} --workers 3 --worker-class gthread --threads 4 --timeout 120 --access-logfile - --error-logfile -'
        ;;
    web-dev)
        # Source: docker-compose.yml `backend`. Dev-only hot-reload runserver.
        # Two INDEPENDENT guards so a single wrong env var (one Railway text box)
        # cannot turn this into a deployed web tier:
        #   1. DJANGO_SETTINGS_MODULE must end in `.dev`.
        #   2. RAILWAY_ENVIRONMENT_NAME must be unset (any deployed env is out).
        case "${DJANGO_SETTINGS_MODULE:-}" in
            *.dev) : ;;
            *) fail "role 'web-dev' refuses DJANGO_SETTINGS_MODULE='${DJANGO_SETTINGS_MODULE:-}' (must end in '.dev'). Use role 'web' for a deployed web tier." ;;
        esac
        if [ -n "${RAILWAY_ENVIRONMENT_NAME:-}" ]; then
            fail "role 'web-dev' refuses to run in a deployed env (RAILWAY_ENVIRONMENT_NAME='${RAILWAY_ENVIRONMENT_NAME}'). Use role 'web'."
        fi
        cmd='python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8777'
        ;;
    worker)
        # Source: docker-compose.yml `worker`.
        cmd='exec celery -A config.celery worker -l info --concurrency=1'
        ;;
    worker-backtest)
        # Source: docker-compose.yml `worker-backtest`.
        cmd='exec celery -A config.celery worker -Q backtest -l info --concurrency=1 --max-memory-per-child=2000000'
        ;;
    beat)
        # Source: docker-compose.yml `beat`.
        cmd='exec celery -A config.celery beat -l info -S redbeat.RedBeatScheduler'
        ;;
    streams)
        # Source: docker-compose.yml `streams`.
        cmd='exec python manage.py run_broker_streams'
        ;;
    ws)
        # Source: docker-compose.yml `ws`. The image sets ENV PORT=8777, so
        # ${PORT:-8788} does NOT fall back — compose's ws service sets PORT=8788
        # (Railway injects $PORT). One variable, correct in both.
        cmd='exec daphne -b 0.0.0.0 -p ${PORT:-8788} config.asgi:application'
        ;;
    *)
        fail "unrecognised SERVICE_ROLE='${role}'."
        ;;
esac

if [ -n "${STP_ENTRYPOINT_DRY_RUN:-}" ]; then
    # Print the command TEMPLATE un-expanded (literal ${PORT}) so the output is
    # identical on a dev host (PORT unset) and inside a container (PORT=8777),
    # and matches the pinned literal exactly. Compare strings, not exit codes.
    printf '%s\n' "${cmd}"
    exit 0
fi

echo "entrypoint: starting SERVICE_ROLE='${role}'" >&2
# Re-expand ${PORT} etc. in a fresh shell (no `set -u`, so an unset ${PORT}
# without a default is empty rather than an error). `exec` hands PID 1 to the
# workload for correct signal handling.
exec sh -c "${cmd}"
