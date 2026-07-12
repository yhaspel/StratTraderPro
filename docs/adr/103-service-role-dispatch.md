# ADR-103 — Service-role dispatch in the image entrypoint (remove the silent-substitution default)

**Date:** 2026-07-12
**Status:** Accepted
**Milestone:** M11 — Hardening, Security, Load Test & Docs
**Reference:** `project-plan/11-hardening-and-load-test.md` §7.0; AC-11-14 [CI], AC-11-15 [LIVE];
`bugs/BUG-011-celery-worker-and-beat-are-not-running-celery.md`;
`docker/entrypoint.sh`, `docker/entrypoint.expected`, `docker/backend.Dockerfile`,
`docker-compose.yml`, `backend/config/test_entrypoint_dispatch.py`,
`scripts/verify_entrypoint_dispatch.sh`, `.github/workflows/ci.yml` (`entrypoint-dispatch`),
`docs/ops/service-role-cutover.md`

## Context

BUG-011 (S1/P0): the Railway services `celery-worker` and `celery-beat` had an
**empty Custom Start Command**, so they ran the backend image's default `CMD` —
`migrate && gunicorn`. Both reported **Online** and ran a *second copy of the
Django web server* for two months. The default `celery` queue therefore had no
consumer and beat never fired a single scheduled task in **either** environment,
including `apps.risk.tasks.daily_loss_watcher` — a risk control.

The root property is not "someone forgot to type a command." It is that **a blank
field silently substitutes a web server.** The service does not fail; it succeeds
at being the wrong thing, and the one alert designed to catch it (`CeleryQueueDepthHigh`)
could not fire for two independent reasons (paused — BUG-009; and its series is
emitted by the worker process that did not exist). *The failure disabled its own
detector.*

BUG-011 was fixed live by typing the correct start commands into the Railway UI.
Those text boxes are exactly what this ADR removes.

## Decision

**Make `SERVICE_ROLE` a required dispatcher in the image entrypoint, and remove the
default.** The image no longer has an opinion about what a container is when
`SERVICE_ROLE` is unset — it exits non-zero.

- `docker/entrypoint.sh` (committed `0755`, copied to `/usr/local/bin/` so the
  `./backend:/app` bind mount cannot mask it) dispatches on `SERVICE_ROLE` across
  **seven** roles: `web`, `web-dev`, `worker`, `worker-backtest`, `beat`, `streams`,
  `ws`.
- **Unset or unrecognised `SERVICE_ROLE` → `exit 1`** with a loud message naming the
  valid roles. **Never a fallback to `web` (or to anything).** That single line is
  the whole point: it converts a silent wrong-process into a crash. A crashed deploy
  is visible in thirty seconds.
- The image `CMD` (not `ENTRYPOINT`, so `docker run <image> <cmd>` still overrides it
  for debugging) is `["/usr/local/bin/entrypoint.sh"]`.
- **Command sources are pinned, not guessed.** The `web` role reproduces the
  Dockerfile's historical gunicorn `CMD` *including* `--access-logfile - --error-logfile -`
  (dropping them silences the web tier's logs). The other six come from
  `docker-compose.yml`. All seven literals live in `docker/entrypoint.expected`.
- **`web-dev` is double-guarded.** It refuses to start unless `DJANGO_SETTINGS_MODULE`
  ends in `.dev` **and** `RAILWAY_ENVIRONMENT_NAME` is unset. Two independent guards
  because BUG-011 was an operator-config error and one env var is one text box away
  from being wrong. `web-dev` exists so the local conversion does not silently swap
  the developer's hot-reload `runserver` for gunicorn.
- **Compose drives every backend-image service through the dispatcher** — the six
  services (`backend`→`web-dev`, `worker`, `worker-backtest`, `beat`, `streams`, `ws`)
  set `SERVICE_ROLE` in `environment:` and carry **no `command:` override**, so the
  path that ships is the path the E2E smoke exercises. `frontend` and `ngrok` keep
  their `command:` (different images, not roles). Compose's `ws` sets `PORT: 8788`
  because the image's `ENV PORT=8777` means `${PORT:-8788}` never falls back.
- **Testable without docker-in-docker:** `STP_ENTRYPOINT_DRY_RUN=1` prints the
  resolved command *template un-expanded* (literal `${PORT}`) and exits 0. The CI
  test asserts each role's output equals its pinned literal (string equality — an
  exit-0 check alone proves nothing, the worthless self-report BUG-009 is made of),
  and that unset/bogus/`web-dev`-misconfig exit non-zero and never resolve to `web`.

## Why `railway.json` config-as-code was rejected (2026-07-11)

It is the tempting middle option and it does not fix the bug class. `railway.json`
version-controls the *value*, but the dangerous **default survives**: the image
`CMD` is still gunicorn. If the config is not applied, is overridden in the UI, or a
new service is added and forgotten, the container silently becomes a web server
again — the identical failure, now with a config file that makes you *believe* it is
covered. It buys reviewability and no safety. Only removing the default removes the
failure.

## Consequences

- **Positive:** a service's identity is version-controlled *and* enforced by the
  image; a missing role crashes loudly instead of impersonating the web tier; the
  shipped path is the tested path (compose + E2E smoke run through the dispatcher);
  the `web` gunicorn boot is proven in CI (`entrypoint-dispatch` job).
- **Cost / migration:** this is inert until the operator cutover (AC-11-15). An
  existing Railway Custom Start Command **overrides the image `CMD`**, so merging
  this ADR deploys the *capability*, not the *change*. The operator must set
  `SERVICE_ROLE` on every service in both environments and **delete every Custom
  Start Command** (`docs/ops/service-role-cutover.md`), staging first. Rollback is
  per-service in seconds: re-type the start command.
- **Interim safety already in place:** M10's dead-man's switch (`TargetDown`,
  `MetricsPipelineDown`) now fires within 5 minutes if a worker/beat stops scraping,
  and a daily scheduled audit re-asserts the beat→queue→worker loop. That detection
  is a backstop, not a fix — the default was still wrong, which is what this removes.
