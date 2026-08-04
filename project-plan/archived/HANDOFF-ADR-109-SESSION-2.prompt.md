# HANDOFF — ADR-109 operator cutover, session 2

> ## ✅ ARCHIVED — CONSUMED 2026-08-02. DO NOT RE-RUN.
>
> Session-2 handoff for the ADR-109 cutover. Everything executable in it was completed:
> live state re-verified, the alert drill confirmed on both channels, the OTLP token shown to be in
> active use, the rollback set audited, the RULE-10 findings applied, and a durable H.3 check armed.
>
> ⚠️ **One instruction in this file is WRONG.** Its H.4 "blocking discovery" — that the feature
> branch deletes the ADR-109 section from `project-plan/PROGRESS.md` and must restore it on merge —
> was disproven by merge simulation: the section survives cleanly, so restoring it would duplicate
> it. Use the **revised** H.4 instruction in
> `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md` (§ "SESSION 2, PART B — B2").


**Feed this to a fresh Claude Code CLI session in `~/Documents/Claude/Projects/StratTraderPro`.**

## ⛔ READ THIS FIRST — the destructive work is DONE. Do not redo it.

A CLI session on **2026-08-02** executed PARTS C–G of
`ONE-SHOT-ADR-109-OPERATOR-CLI.prompt.md` in full against **live production**. 12 alert rules, a
folder, a contact point, 3 dashboards and 2 Railway services were **deleted**. Re-running that
prompt from the top would try to delete things that no longer exist and would misreport the result.

**Full evidence: `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md` (1375 lines, uncommitted).**
Read it before acting. The "EXECUTION LOG — 2026-08-02, CLI session" section onward is session 1.

## ⚠️ Do NOT re-set the old `/goal`

Session 1 was run under `/goal implement ONE-SHOT-ADR-109-OPERATOR-CLI.prompt.md as it is written.
Autonomously`. That goal is **unsatisfiable by construction**: the prompt's PART H closes only after
a trading day plus a day-2 audit (Tue 2026-08-04). The Stop hook looped ~8 times, each iteration
correctly concluding the same thing. **Do not re-set that goal.** If you want a goal, scope it to
what is actually executable, e.g. *"verify the ADR-109 PART H soak and report"*.

## Verified state (2026-08-02 15:37 IDT — re-verify before trusting)

```
rules      : 11   paused: []          dashboards (stp-*): 3
targets    : backend, beat, streams, worker, worker-backtest   (up == 0 -> 0 results)
budget     : 0.103   (< 0.85)          firing: []
branch     : feat/data-provider-keys-ui   tracked files modified: 0
```

## Credentials — how to authenticate

The Grafana token is in **`.env.grafana`** at the repo root (`chmod 600`, gitignored via `.env.*`).

**It is NOT auto-loaded** — Claude Code's Bash tool sources a shell snapshot, not your rc files.
Source it explicitly in every command:

```bash
cd ~/Documents/Claude/Projects/StratTraderPro
set -a; . ./.env.grafana; set +a
g() { curl -sS -H "Authorization: Bearer $GRAFANA_TOKEN" "$GRAFANA_URL$1"; }
```

⚠️ The token is a Grafana **service account** token (`glsa_`, role Admin) with **NO EXPIRATION**.
Nothing revokes it automatically — see teardown below. A `glc_` token is a Cloud Access Policy
token for grafana.com and will **401** against the stack API.

Railway CLI is installed and logged in; the project is linked (`StratTraderPro` / `production`).

## What is left

### 1. PART H — the soak (the only remaining prompt work)

- **Mon 2026-08-03** — soak day 1. Watch for anything unexpectedly firing, and more importantly
  **anything that should have fired and did not.**
- **Tue 2026-08-04** — H.3: confirm the daily audit run is green.
  - Green looks like exactly: `OK — 6/6 checks passed.`
  - The audit is a desktop scheduled task, `cron 0 9 * * *`, enabled, and runs independently of any
    Claude session. Registry:
    `~/Library/Application Support/Claude/local-agent-mode-sessions/6b708088-141f-40a1-ae49-68ebbd14ed2b/504f3a1c-a3bf-4e49-9a25-0b6cd29f3569/scheduled-tasks.json`
    Prompt: `~/Documents/Claude/Scheduled/strattraderpro-silent-failure-audit/SKILL.md`
    (rewritten 2026-08-02 to the reduced shape; 13086 bytes).
- **H.4** — the exact replacement wording for `PROGRESS.md`'s two `⏳ PENDING` lines is **already
  written** in the report. **Do not flip them until H.3 is green.**

⛔ **Blocking discovery for H.4:** the branch `feat/data-provider-keys-ui` **deletes the entire
`## The 2026-08-01 observability rightsizing (ADR-109)` section** from `PROGRESS.md` (18 lines,
including both PENDING markers). It was cut before PR #50. Merging as-is erases the ADR-109 record.
Restore that section on merge, *then* apply the H.4 wording. Flagged, not fixed — session 1 made no
repo commits.

### 2. Owner actions still outstanding

1. **Confirm the alert drill actually delivered.** Grafana showed both alerts reach `Alerting`,
   which proves routing, not receipt:
   - `CeleryQueueDepthHigh` (warning) `activeAt 2026-08-02T08:18:50Z` → **operator-email only**
   - `MetricsBudgetExhausted` (critical) `activeAt 2026-08-02T08:31:10Z` → **Telegram + email**
   Both are recorded as **SENT, not CONFIRMED**. Check the chat/inbox and update the report.
2. **Rotate the exposed `strattraderpro-otlp` Cloud Access Policy token** (org `1752334`, region
   `prod-eu-central-0`) — it was pasted into a chat transcript. Check what is pushing OTLP with it
   *before* deleting; mint a replacement on the same policy first if it is in use.
3. **Decide on the Redis password.** A name-based redaction filter missed `REDIS_ADDR` and printed
   the live Redis URI to a terminal. It was re-redacted on disk within a minute and the backup
   directory re-scanned clean. Exposure is limited — `redis.railway.internal` is private-network
   only — but rotation is the clean fix (requires updating backend, workers, beat, streams).

### 3. Teardown — REQUIRED when the soak closes

```
1. https://yuval3000.grafana.net/org/serviceaccounts  -> delete the `adr109-cutover` service
   account. This is the ONLY thing that revokes the token (no expiry was set).
2. rm .env.grafana
```

### 4. Repo findings flagged, never fixed (developer's call, RULE 10)

- `infra/grafana/system-health-dashboard.json` panel 8 description still references "the Auth Health
  board's `bad_password` counter" — a dangling reference to a board deleted 2026-08-02.
- Four runbooks still point at the deleted Auth Health dashboard: `user-locked-out.md:45`,
  `password-reset-abuse.md:56`, `user-lost-mfa.md:93`, `prod-bootstrap.md:152`.
- `bugs/README.md:31` records BUG-009 as "FIXED (all 21 live)" — now wrong; live count is 11.
- `setup-guides/grafana-setup.md:67` gives `strattraderpro.grafana.net`, which does not resolve.
- AC-R5 wording should say `StratTraderPro/stp-alert-rules.prom.yaml` (rules live in a nested
  subfolder, uid `alerting-34szz3tqd4u0g`; this is intended, not drift).
- `stp-adr109-backup-2026-08-01/` is **not gitignored**.
- Grep for `clamp_min` in any other ratio denominator — it turns idleness into 100% failure. That
  defect is what made the deleted `auth-login-success` rule fire on *absence* of login traffic.

## Environment gotchas that cost session 1 time

1. **`UID` is readonly in zsh.** `UID=$(...)` fails with "bad math expression". Use another name.
2. **BSD `head` has no `head -n -1`.** It errors and produces an **empty** file — and `cmp` on two
   empty files reports success. Session 1 nearly recorded a false pass this way. Guard every
   extraction with a non-empty check before believing a comparison.
3. **Redact secrets by VALUE shape, not key name.** Match `://user:pass@`, not
   `PASSWORD|SECRET|TOKEN`. `REDIS_ADDR` matches none of the latter.
4. **`git show origin/main:<path>`** reads post-#50 files without checking out `main` — the working
   tree is on a feature branch and another session may be using it.
5. **Rule expressions embed their own threshold** (`max(celery_queue_depth) > 1000`). Querying the
   full expression returns empty when not breaching — that means "not firing", **not** "no data".
   Strip the comparison to test whether the input actually has samples.
6. **`/api/folders` returns top-level folders only.** Resolve subfolders with `/api/folders/{uid}`.
7. **Railway did not auto-redeploy on `variable delete`** — contrary to the original prompt. It did
   not matter: `agent.yaml@5fafff0` references only the five task targets, so the deleted exporter
   vars were inert. Verified by reading the config, not assumed.
8. **Claude desktop scheduled tasks are plain files** — no Screen Recording permission needed. See
   the paths in §1. Driving the desktop *UI* would need macOS Accessibility + Screen Recording
   attributed to **Visual Studio Code** (Claude Code runs under it), but the file route avoids that
   entirely.

## Rules that still bind

- `X-Disable-Provenance: true` on **every** write (`POST`/`PUT`/`DELETE`), or Grafana marks the
  object read-only forever.
- **Never touch, in either direction:** `scrape_interval: 60s`; the `MetricsPipelineDown` /
  `TargetDown` dead-man's pair; `contact-points.yaml` / `notification-policy.yaml`; the
  `operator-email` / `operator-telegram` receivers; `BACKEND_TARGET` / `METRICS_BASIC_AUTH_*` and
  the four task-target env vars. Never alert on `grafanacloud_org_metrics_billable_series`.
- **Never print secrets.** Not the Grafana token, not the Telegram bot token in
  `operator-telegram.settings`. **Never set `ENABLE_LIVE_TRADING=true`.**
- **No repo commits, PRs or merges.** The report file is for the human to commit.
- If any verification returns something other than stated — or any rule comes back
  `isPaused: true` — **STOP and report.** Do not improvise.

## Rollback, if the soak goes wrong

Everything deleted is backed up in `stp-adr109-backup-2026-08-01/` (verified readable):

| file | what |
|---|---|
| `adr109-rules-backup.json` | all 23 pre-cutover rules, full restorable bodies |
| `deleted-rule-bodies.jsonl` | the 12 deleted rules, one JSON per line |
| `adr109-dashboard-stp-*.json` | all 6 pre-cutover dashboards |
| `deleted-contact-point-auth-health-email.json` | the deleted contact point |
| `daily-audit-prompt-BEFORE.md` | the pre-rewrite audit prompt (sha256 `367e450a…`) |
| `railway-exporter-services-manifest.json` | image + digest + region + replicas |
| `worker-metrics-scrape-6b7059c.md` | exporter provisioning recipe |
| `deleted-grafana-agent-vars.json` | the two deleted env var values |

⚠️ **Rules recreate with `POST /api/v1/provisioning/alert-rules`, not `PUT`** — a deleted uid no
longer exists, so `PUT` returns 404. Re-created rules can arrive **paused**; re-check.
⚠️ The B.5 runbook says `postgres-exporter.railway.internal` / `redis-exporter.railway.internal`;
the **live values carried a `-prod` suffix**. Use `deleted-grafana-agent-vars.json`, not the runbook.
