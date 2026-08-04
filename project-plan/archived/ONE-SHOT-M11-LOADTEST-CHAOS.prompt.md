> **⚙️ SPENT ONE-SHOT — milestone shipped; not a work item.**
> This is the agent prompt that built a now-merged milestone. Moved out of the active plan on
> 2026-07-14 (OSS pivot) and kept for historical record only — **do not re-run.** The durable record
> of what shipped lives in `project-plan/PROGRESS.md` and the matching `M*-EXECUTION-REPORT.md`.

---

# ONE-SHOT — M11 load test + chaos drills (AC-11-3, AC-11-4, AC-11-5, AC-11-6)

**Run on:** the operator's mac, with Docker. Not the Cowork sandbox (no Docker daemon there).
**Time:** ~1 hour, most of it waiting on two 10-minute Locust runs.

**Why this exists.** These four ACs are tagged **`[CI]`** — they are *definition of done* for M11,
not operator extras. The harness was committed in M11 (`72ed231`) and **never run**. Verified
2026-07-13: `docs/ops/load-test-results.md` and `docs/ops/chaos-drill-logs.md` are untouched since
that commit, contain **only methodology and zero measurements**, and the results doc still says
*"PARKED (operator runs on a dedicated stack) — why the full run is not executed here."*
**M11 cannot honestly close with four of its own ACs unrun.**

**Bonus:** AC-11-4 is *also* **M13 §6 gate 2** — the kill-switch-under-load evidence that must exist
before `ENABLE_LIVE_TRADING` is ever flipped. One task, two milestones. This is the highest-value
work left on the project.

---

## 0. RULES

1. **A dedicated, throwaway compose stack. Never the shared dev stack.** `scripts/chaos/_lib.sh`
   refuses `PROJECT=strattraderpro` unless `FORCE_SHARED=1`. **Do not set that flag.** These drills
   SIGKILL Redis, crash-loop `streams` and restart Postgres.
2. **Never point any of this at staging or production.** The fake-broker seam is local-only.
3. **`exit 0` is not a pass.** Every drill prints `[ASSERT]`/`[PASS]`/`[FAIL]`. **Read the numbers.**
   This project's entire bug history is components that reported success while doing the wrong thing
   (BUG-008/009/011). A drill that "ran fine" and produced no measurement proves nothing.
4. **The deliverable is the EVIDENCE, not the run.** An AC is done when a **measured number** sits in
   the results doc — not when a script exited 0.
   > ⚠️ **Do NOT grep the docs for the word "pending" as a done-check.** Both files legitimately
   > contain `pending_delete_at` and `PENDING_SUBMIT` as ordinary prose. The real check is:
   > **does the doc contain p50/p95/p99 numbers and dated PASS/FAIL outcomes?** Today it does not.
5. **If a drill fails, report the failure.** Do not tune a threshold to make it pass. **A failing
   kill-switch drill is the single most valuable result this milestone can produce** — it would mean
   the platform cannot get a user flat under load, which is the whole reason the kill switch exists.

---

## 1. The two flatten numbers are DIFFERENT MEASUREMENTS — do not conflate them

| Bar | What it measures | Where it lives | Is it in scope here? |
|---|---|---|---|
| **p99 ≤ 5 s** | **single-user** flatten (click → last submit) | AC-08-8 / `docs/slo.md` SLO 4 — an **ongoing production SLO**, measured from the `killswitch_flatten_latency_seconds` histogram | Not a drill. Report the histogram if you scrape it, but this run does not pass/fail on it. |
| **p99 ≤ 8 s** | **50-user simultaneous** L1 flatten, under concurrency | **AC-11-4** | ✅ **This is the bar this run is graded on.** |

Deliberately looser under load. `docs/ops/load-test-results.md` says so:
*"p99 ≤ 8s (per-user ≤5s p99, AC-08-8)"*.

**So a 6 s result on the 50-user run is a PASS, not a failure. Do NOT tighten AC-11-4 to 5 s.**
(An earlier draft of this prompt wrongly claimed these two were in conflict. They are not. The real
error was in M13 AC-13-10, which applied the per-user bar to the concurrent scenario — **already
corrected** in `project-plan/13-live-trading-switch.md`; nothing to do about it here.)

---

## 2. Stand up the dedicated stack

> **The "PARKED" blocker in `docs/ops/load-test-results.md` is STALE — ignore it.** It claims seeding
> is blocked because `users.0005_delete_flow_and_terms` was unapplied (`users_user.pending_delete_at`
> missing → every ORM `User` query raises `ProgrammingError`). That migration **applied 2026-07-13**
> during the SERVICE_ROLE cutover (`Applying users.0005_delete_flow_and_terms... OK` in the backend
> boot log), and a fresh dedicated stack runs `migrate` on boot regardless.
> **Nothing is standing in the way of this run.** Delete that stale paragraph when you write up the
> results.

```bash
export PROJECT=stp-load
docker compose -p "$PROJECT" up -d --build
```

**Two prerequisites that fail SILENTLY if you get them wrong — check both:**

- **Redis cache backend, not LocMem.** The heartbeat and the `idempotency_key` SETNX guard are shared
  across web/worker/streams. Under LocMem each process gets its own dict, so
  **`redis-kill.sh`'s "no duplicate orders" assertion becomes meaningless while still reporting
  PASS.** Run the stack with prod-shaped settings, or point `CACHES` at `django-redis`.
  **Verify before trusting any AC-11-5 result.**
- **The FakeBrokerAdapter seam.** `STP_LOADTEST_FAKE_BROKER=1` + `PYTHONPATH=/app/loadtest` on
  **backend, worker AND streams**. Without it, `build_adapter` reaches for real Alpaca with junk keys
  — noisy and non-deterministic.

Seed (access tokens are ~15 min TTL — **start the run promptly or re-seed**):

```bash
docker compose -p "$PROJECT" exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 PYTHONPATH=/app/loadtest \
  python /app/loadtest/seed.py --count 100 --with-broker

python -m venv /tmp/lt && /tmp/lt/bin/pip install -r backend/loadtest/requirements.txt
export LT_FIXTURES=backend/loadtest/fixtures.json
```

`fixtures.json` holds per-user JWTs **and TOTP secrets** — do not commit it (confirm it is
gitignored) and delete it at teardown.

---

## 3. AC-11-3 — sustained load (100 WS dashboards + 20 webhooks/sec, 10 min)

```bash
/tmp/lt/bin/locust -f backend/loadtest/locustfile.py WsDashboardUser \
  --headless -u 100 -r 20 -t 10m

/tmp/lt/bin/locust -f backend/loadtest/locustfile.py WebhookUser \
  --headless -u 20 -r 20 -t 10m --exit-code-on-error 1
```

| # | Assertion | Read it from |
|---|---|---|
| a | **Zero 5xx** for the whole run | Locust failure table (`WebhookUser` fails on non-200/429) |
| b | **p95 ingest → order-submit ≤ 1.5 s** | `order_submit_latency_seconds` on the **worker's** `:9101/metrics` — **not** Locust's client-side latency. Locust times the HTTP ack; the AC measures the **platform path** (webhook → Celery → submit). Getting this wrong is the easiest way to record a number that looks great and means nothing. |
| c | `celery_queue_depth{queue}` returns to ~0 after the run (no unbounded backlog) | worker `:9101/metrics` |
| d | WS reconnect rate not pathological | Locust `WS connect` / `WS reconnect` rows |

The worker metrics port is **not host-published** — scrape from inside the network:

```bash
docker compose -p "$PROJECT" exec -T worker \
  sh -c 'curl -s localhost:9101/metrics' | grep -E 'order_submit_latency|celery_queue_depth'
```

> **Do not** assert on `process_*` / `django_db_*` — they are disabled under multiprocess gunicorn
> (known dead end; see MEMORY.md).

---

## 4. AC-11-4 — 50-user simultaneous L1 halt + flatten ⭐ (also M13 §6 gate 2)

**The most important measurement on this project.** It is the only evidence that the kill switch
actually works under load — on a platform whose circuit breakers had **never once executed in
production** until BUG-011 was fixed on 2026-07-11.

```bash
docker compose -p "$PROJECT" exec -T backend \
  env STP_LOADTEST_FAKE_BROKER=1 STP_LOADTEST_FAKE_SEED_POSITION=1 PYTHONPATH=/app/loadtest \
  python /app/loadtest/flatten_50.py --users 50
```

**Assertions:**

- All 50 users' flatten orders **submitted within 10 s**.
- **p99 ≤ 8 s** (AC-11-4 — see §1; do **not** grade this against the 5 s per-user SLO).
- Report **p50 / p95 / p99**, not just the max.
- Also scrape `killswitch_flatten_latency_seconds` from the worker — it is the histogram
  `docs/slo.md` SLO 4 is computed from, so it connects this drill to the published SLO.

### Second run: LIVE-mode accounts (M13 gate 2)

Re-run with the seeded `BrokerAccount` rows set to **`mode=LIVE`**, so the M13 plumbing
(`BrokerAccount.mode` → `BrokerContext.mode` → adapter/stream selection) is exercised end-to-end
under load.

**Write down precisely what this does and does not prove:**

- ✅ Proves the **flatten SLO holds under load** and that the **mode plumbing does not break the
  kill-switch path**.
- ❌ Proves **nothing** about Alpaca's live endpoint. `fake_broker_patch.py` replaces `build_adapter`
  wholesale, so `AlpacaAdapter` — and therefore its live gate and key validation — **never executes**.
  **No load test on this platform touches a real broker, by design.**

Record that caveat verbatim in the results doc. Otherwise a future reader will believe live trading
was load-tested against Alpaca. It was not, and it must not be.

---

## 5. AC-11-5 — chaos: Redis killed mid-traffic

```bash
PROJECT=stp-load scripts/chaos/redis-kill.sh
```

**Assertions:** Celery recovers **≤ 60 s**; **no orphaned or duplicate orders**; at-most-once
semantics hold (the `idempotency_key` SETNX guard + Alpaca `client_order_id`).

⚠️ **A PASS here is worthless if `CACHES` is LocMem** (§2). Confirm Redis is the cache backend first.

---

## 6. AC-11-6 — chaos: `run_broker_streams` killed

```bash
PROJECT=stp-load scripts/chaos/streams-kill.sh
```

**Assertions:** `GET /api/v1/brokers/{id}/status/` flips to **DEGRADED ≤ 60 s**
(`BROKER_STREAM_HEARTBEAT_TTL` 45 s + margin); **L1 flatten still works via the REST path**
(independent of the stream); missed fills recovered on restart via the REST cursor and **deduped on
`broker_exec_id`**.

> After AC-11-4 this is the drill that matters most for live trading: *the fill stream died — can the
> platform still get you flat?*

---

## 7. The remaining §7.5 drills (not AC-gated — run them anyway)

```bash
PROJECT=stp-load scripts/chaos/worker-kill.sh        # idempotent retry — no duplicate orders
PROJECT=stp-load scripts/chaos/alpaca-5xx-storm.sh   # bounded retry — no duplicate orders
PROJECT=stp-load scripts/chaos/db-restart.sh         # app reconnects unaided; measure downtime
PROJECT=stp-load scripts/chaos/role-removal.sh       # AC-11-14 — non-destructive, safe anywhere
```

`role-removal.sh` re-proves the guard BUG-011 needed. It should already pass (it is also a CI job).

---

## 8. Record the evidence — THIS is the deliverable

**`docs/ops/load-test-results.md`**
- AC-11-3: 5xx count, **p50/p95/p99 ingest→submit** (from the worker histogram), queue-depth recovery.
- AC-11-4: flatten **p50/p95/p99 vs the ≤8 s bar**, plus the LIVE-mode re-run and the §4 scope caveat
  **verbatim**.
- Delete the stale "PARKED" paragraph (§2) and the stale `users.0005` blocker.

**`docs/ops/chaos-drill-logs.md`**
- One dated entry per drill: what was broken, measured recovery time, assertion outcome, and any
  orphaned/duplicate-order findings.

**Then update the trackers:**
- `project-plan/PROGRESS.md` + `plan-progress-tracker.md` — AC-11-3/4/5/6.
- `project-plan/13-live-trading-switch.md` §6 — **tick gate 2** if AC-11-4 passed. (AC-13-10's wording
  is already fixed — do not re-edit it.)

---

## 9. Where M11 stands after this

| AC | Before | After |
|---|---|---|
| AC-11-3 | ❌ never run | measured |
| AC-11-4 | ❌ never run | measured (**+ M13 gate 2**) |
| AC-11-5 | ❌ never run | measured |
| AC-11-6 | ❌ never run | measured |

**Still open — all human-gated, none CLI-doable:**
**PART F** (`seed_terms` — **legal sign-off; the long pole. Send the ToS/Privacy drafts to counsel
NOW, in parallel with this run**) · **PART G** (audit-role design decision) · **PART C** (Cloudflare
R2 — secrets) · **PART D** (DB password rotation — maintenance window) · **PART H** (prod bring-up —
domain purchase). AC-11-12's FCP miss is owned by **M14** (`14-frontend-first-paint.md`) and is not a
release blocker.

---

## 10. Tear down

```bash
docker compose -p "$PROJECT" down -v
rm -f backend/loadtest/fixtures.json     # per-user JWTs + TOTP secrets
```
