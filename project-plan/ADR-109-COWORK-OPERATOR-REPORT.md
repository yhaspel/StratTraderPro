# ADR-109 Operator Run — Cowork Execution Report

**Run started:** 2026-08-01 ~23:00 IL · **Report as of:** 2026-08-02 ~06:10 IL
**Operator:** Cowork cloud session (browser-driven, `mac-home` Chrome)
**Code half:** PR #50, squash `5fafff0` — **verified present on `origin/main`**
("chore(observability): reduce Grafana to the safety core (ADR-109) (#50)", 2026-08-01 21:42 +0300)
**Stack:** `https://yuval3000.grafana.net` (org "Main Org.")

**Status: PARTS A and B done (non-destructive). PARTS C–H NOT STARTED — stopped at the
first gate that needs the user.** Nothing has been deleted, imported, un-paused, re-pointed
or redeployed. Production is in exactly the state it was in before this session began.

---

## HEADLINE: the auth alert is a defective rule, not an auth problem — and it is worse than "benign"

**Verdict: BENIGN. Retire it knowingly under ADR-109.** But the reason is not the one the plan
anticipated, and it is worth writing down because the same defect pattern can recur.

The plan's hypothesised benign explanation was "a tiny denominator — two or three failed logins
in a quiet week drag the ratio under 0.95". **That is not what happened.** There were no failed
logins at all.

### What the rule actually is (read from the provisioning API, not from the docs)

```
uid   : auth-login-success            (creation-time name survives as the UID)
title : "Auth login success rate < 95%"   ← title was edited since creation; the plan's
                                             `auth-login-success` name is the UID, not the title
group : auth-health   folder: StratTraderPro Auth (cfkrwjgh3sxkwa)
for   : 5m   severity: warning   noDataState: OK   execErrState: Alerting   isPaused: false
expr  : sum(rate(auth_login_total{result="ok",service="backend"}[5m]))
        / clamp_min(sum(rate(auth_login_total{service="backend"}[5m])), 0.0001)
cond  : lt 0.95
```

**The live expression is not the one the prompt predicted.** The prompt expected a plain
`sum(...) / sum(...) < 0.95`. The live rule wraps the denominator in **`clamp_min(..., 0.0001)`**.
That single defensive call is the entire defect.

### The mechanism

`clamp_min` was presumably added to avoid a divide-by-zero. What it actually does:

| Situation | Without `clamp_min` | With `clamp_min` |
|---|---|---|
| Logins happening, some failing | real ratio | real ratio |
| **No logins at all in the window** | `0 / 0` = NaN → empty → NoData → `noDataState=OK` → **Normal** | `0 / 0.0001` = **0** → `0 < 0.95` → **FIRES** |

So the rule **fires on absence of login traffic, not on login failure.** On a single-user,
mostly-idle instance that is the normal state of the world, which is why it sat firing for ~40h.

### The evidence

Queried against `grafanacloud-yuval3000-prom`:

- **`increase(auth_login_total[7d])` → `result="ok": +4.00`, and nothing else.**
  Four logins in seven days. **Zero failures. Success rate = 100%.**
- **Rule expression over 48h, step 5m: 479 samples, all of them exactly `0.0000`.**
  Not "sometimes below 0.95" — *never anything but zero*. Distinct observed values: `{0.0000}`.
- **Series history over 30d** — only three label values have *ever* existed:

  | `result` | total | last seen |
  |---|---|---|
  | `ok` | 3 (counter value) | 2026-08-01T17:57Z |
  | `bad_password` | 1 | 2026-07-19T12:57Z |
  | `unverified` | 12 | 2026-07-19T12:57Z |

  **No failed login of any kind in the last ~13 days.** The only `bad_password` event ever
  recorded was on 2026-07-19.

### The "recovery" was also an artifact

The rule currently reads `state: inactive` — it is **not** firing, contradicting what the
2026-08-01 audit run reported and what the plan assumes. It did not recover because auth improved.
**`auth_login_total` has no series at all right now.** The last sample was ~2026-08-01T17:57Z; the
rule went inactive at 18:47:40Z. Empty result → NoData → `noDataState=OK` → Normal.

Most likely cause: the backend restarted, and `prometheus_client` only creates a labelled counter
child on first increment — so with nobody logging in since, the series does not exist yet. (Yuval's
current session is refresh-token based; refreshes do not increment `auth_login_total`.) I could not
confirm the restart time from `process_start_time_seconds{job="backend"}` because multi-process
gunicorn suppresses `process_*` metrics — a known gotcha, not a new finding. **Flagged as a
hypothesis, not a verified claim.**

So both the firing *and* the recovery were artifacts. The rule has never once measured a real
authentication problem.

### Escalation triggers (PART A.5) — none met

From the audit chain (`/admin/audit`, 184 events) and the metrics above:

- **"One email locked repeatedly from many different IPs"** — no lockout events at all.
- **"Failures faster than a human could type"** — no failures in the window.
- **"Lockouts hit an account the user did not expect"** — none.

A lockout is **logically impossible** here: `user-locked-out.md` documents lockout as 10 failures
in a 15-minute sliding window, and there has been exactly **one** failed login in 30 days. This is
a proof, not a sampling — I did not need to enumerate all 8 pages of audit events to close it.

Login events observed: 3× `Login succeeded` in one minute on 7/30 20:49 + `Oauth login ok` on 7/30
and 8/1, **all from `77.137.23.100`** (one Israeli consumer IP — consistent with the account owner).
`Verifier completed` ran 7/31 11:00 by `audit_verifier`, consistent with `AuditIntegrityFailure`
being Normal.

### Recommendation

Deleting this rule under ADR-109 is not merely safe — **it removes a false-positive generator.**
Retire it knowingly. If auth-success monitoring is ever wanted again, the fix is to drop
`clamp_min` and let NoData mean "nobody logged in", or to gate on a minimum denominator
(`and sum(rate(auth_login_total[5m])) > 0`). **That is a repo change, not a Cowork change.**

---

## HEADLINE 2: two of the plan's assumptions are wrong, and one of them breaks PART C's gate

### (a) The 20 code-managed rules are NOT in the `StratTraderPro` folder

They are in a **nested subfolder**: `StratTraderPro / stp-alert-rules.prom.yaml`
(uid `alerting-34szz3tqd4u0g`), created by a previous converter import that named the folder after
the uploaded file. Confirmed in the API *and* visually in Alerting → Alert rules.

Two consequences:

1. **PART C.4's gate is wrong as written.** It asserts
   `folders: MUST be ['StratTraderPro']`. Today it would return `['alerting-34szz3tqd4u0g']` —
   and worse, `/api/folders` does **not** list that subfolder at all (it returns only the three
   top-level folders), so `byUid[...]` falls through to a raw UID. The gate needs to resolve
   nested folders via `/api/folders/{uid}` or accept `StratTraderPro/stp-alert-rules.prom.yaml`.
2. **⛔ A fresh import would not reconcile — it would duplicate.** Uploading `alert-rules.yaml`
   creates a *new* subfolder named `alert-rules.yaml` and leaves `stp-alert-rules.prom.yaml`
   standing with all 20 of its rules. The end state would be ~31 rules across two subfolders,
   not 11. **The import path as written does not reach the stated end state.**

### (b) PART E's target state is already live

`count by (job, env) (up)` **already returns exactly 5 series** — `backend`, `beat`, `worker`,
`worker-backtest`, `streams`, all `env="production"` — and `up == 0` returns no data.

The two exporter jobs are **already unscraped**. Railway auto-deployed `grafana-agent` from the
merged commit when #50 landed. So **PART E.1 has effectively already happened, in the correct
order** (agent redeployed while the exporter services still exist ⇒ RULE 4 / plan D-R8 satisfied
by accident rather than by design, but satisfied).

This also settles the prompt's flagged uncertainty: **"production is the only environment" is
now VERIFIED** — by PART E.2's own query, which is the proof the prompt asked for. No `env` value
other than `production` appears.

What remains in PART E is only: remove the stale `POSTGRES_EXPORTER_TARGET` /
`REDIS_EXPORTER_TARGET` vars, and delete the two exporter Railway services (irreversible → gated).

---

## Live state as found (all read-only, nothing changed)

| Thing | Found | Target | Status |
|---|---|---|---|
| Alert rules | **23**, `isPaused: []` (none paused) | 11 | pending PART C |
| — in `StratTraderPro/stp-alert-rules.prom.yaml` | 20 | — | nested subfolder (see above) |
| — in `StratTraderPro Auth` | 3 | 0 | pending PART C.3 |
| StratTraderPro dashboards | **6** (`stp-*`) | 3 | pending PART D |
| Other dashboards | 13 Grafana-Cloud-managed (Usage Insights, Cardinality, Billing…) | untouched | PART D's "exactly 3" means the `stp-*` set |
| `up` targets | **5**, all healthy, `production` only | 5 | ✅ **already met** |
| `up == 0` | no data | no data | ✅ **already met** |
| Budget rate | **0.11685** | < 0.85 | ✅ **already met, 7× under** |
| `active_series` / `included_series` | 1,179 / 10,000 | — | baseline |
| Contact points | `auth-health-email`, `operator-email`, `operator-telegram` | 2 | pending PART C.3 |
| `scrape_interval` | `60s` (RULE 8 ground truth) | `60s` | ✅ unchanged |

**Datasource names — settled (the docs all disagreed):**

- Prometheus: name **`grafanacloud-yuval3000-prom`**, **uid `grafanacloud-prom`**, `isDefault: true`.
  None of the three documented guesses was right as a *name*; `grafanacloud-prom` is right as a *uid*.
- Usage: name **and** uid both `grafanacloud-usage`.

**Already-correct detail worth noting:** `MetricsBudgetHigh` and `MetricsBudgetExhausted` are
**already bound to `grafanacloud-usage`** live. The "silent-green wrong-datasource" trap that
PART C.1 warns about is currently *avoided*. A re-import is what would put that at risk.

**Notification policy tree (captured):**

```
default receiver: operator-email
  ├─ severity = critical         → operator-telegram   (continue: true)
  └─ severity =~ critical|warning → operator-email
group_by=[grafana_folder, alertname]  group_wait=30s  group_interval=5m  repeat_interval=4h
```

Two things follow:

- **`auth-health-email` is an orphan** — no route references it. PART C.3's delete will **not** be
  refused by Grafana, and the "STOP if a route still references it" branch does not apply.
  (It also means the auth rules were never actually delivering through it; they routed via
  `operator-email` / `operator-telegram` on their `severity` labels like everything else.)
- The PART F label-flip drill path is **valid**: `severity=critical` genuinely fans out to
  Telegram *and* (via `continue: true`) email.

---

## PART A — **DONE.** Verdict above.

Done in full, before anything was deleted (RULE 5 honoured). One deviation from the script:
**step 2 was not performed as written.** I did not screenshot `/d/stp-auth-health` over 14 days,
because the metric-level evidence (7d counts, 48h expression trace, 30d label history) is strictly
stronger than reading the same series off a dashboard, and the dashboard still exists so nothing
was lost by deferring it. Say the word and I'll capture it before PART D deletes it.

**Discrepancy against what the user reported, per PART A.1's instruction to report it:** Yuval
confirmed the alert as still firing. **It is not firing now** and has been inactive since
2026-08-01T18:47:40Z. Both of us were working from the 08-01 audit run, which was accurate when
written. The rule flaps with idleness, so "is it firing" is not a stable question for this rule —
which is itself part of the finding.

## PART B — **DONE for what matters; the full-artifact read-back is NOT satisfied.** Read honestly.

### What is verified

**`adr109-auth-rules-backup.json` — the only cloud-only, non-reconstructible objects — is
captured and integrity-verified end-to-end.**

```
length          : 3629 bytes (browser-reported 3629)
sha256 (browser): 198a04755c04bc299c48f0f5bd3268d2ac4d21641741a23da26c440da02818eb
sha256 (on disk): 198a04755c04bc299c48f0f5bd3268d2ac4d21641741a23da26c440da02818eb   MATCH
parses as JSON  : yes — 3 rules, all isPaused:false
                  auth-login-success / auth-family-revocations / auth-rate-limit-spike
```

This is a real read-back, not a self-report: the hash was computed independently in the browser
and again on the reassembled file, and they match byte-for-byte.

**Also captured and verified:** the folder list, the notification policy tree (above), and the
contact-point inventory.

### Drift diff — the precondition for the PART C decision

I diffed **all 11 keeper rules** live-vs-`5fafff0` on group, `for`, `severity` and expression:

```
KEEPERS matched exactly: 11/11
MISSING from live: none
DRIFT: NONE — live == committed YAML for all present keepers
```

**There is zero drift.** This is the condition the prompt requires before delete-in-place may
even be offered.

### What is NOT satisfied — stated plainly

The **full 23-rule export** (`adr109-rules-backup.json`) was downloaded via the browser to
**`~/Downloads`**, which is **not a folder connected to this session**. I therefore **cannot open
it**, and per the prompt's own standard *"a backup you have not opened is not a backup"* — so
**PART B's read-back gate is NOT green for that file**, and its ⛔ still binds:

> ⛔ Nothing may be deleted anywhere in PARTS C–E until this read-back passes.

I am respecting that. This is a large part of why nothing was deleted.

**Why it went to `~/Downloads` and not the project folder:** the browser tool caps returned output
at roughly 1 KB per call, and the full export is ~48 KB — pulling it through the session would take
~40 round trips. The 3.6 KB auth-rules subset was small enough to pull and verify properly, so I
prioritised the objects that git cannot restore.

**Also not done, and both need you:**

- **B.3 dashboards** — the 6 cloud JSONs were requested via the same download path; unverified for
  the same reason. The repo has committed copies of the 3 keepers, but the 3 being *deleted*
  (`stp-auth-health`, `stp-data-pipelines`, `stp-backtest-ops`) were removed from the repo by #50,
  so **the cloud copy is the only copy** — these matter.
- **B.4 Railway screenshots** and **B.6 the current daily-audit prompt** — not captured; both need
  either your Railway session or the desktop app.

**⚠️ Secret handling:** `adr109-contact-points.json` contains the live **Telegram bot token** in
`operator-telegram.settings`. I did not pull it into the session and have not written it into any
file I am handing you. If you want that export on disk, download it yourself — and do not commit
it. Nothing in this report or its sibling files contains a credential.

## PARTS C, D, E, F, G, H — **NOT STARTED.** Gated on you.

Not blocked by anything technical. Blocked because every remaining step is either destructive or
needs a confirmation you have to give in person (RULE 6), and because PART B's read-back gate is
not green.

---

## Decisions I need from you

1. **PART C path.** I recommend **delete-in-place**, and the evidence for it is now much stronger
   than "lower risk":
   - Drift is **zero** (11/11 exact) — so re-importing reconciles *nothing*. Its only stated
     benefit does not exist here.
   - The import path **does not reach the target state** — it would create a second subfolder and
     leave the existing 20 rules behind (~31 rules, not 11).
   - Import would re-open the BUG-009 paused window (RULE 3: production with zero alerting) for
     no gain, and would put the currently-correct `grafanacloud-usage` binding at risk.

   Delete-in-place = 12 `DELETE`s (9 retired + 3 auth), no paused window at all.
   **The cost, stated as the prompt requires: any live drift would go undetected — but I have
   measured it and there is none.**

2. **The `~/Downloads` backup.** Easiest fix: move `~/Downloads/adr109-*.json` into
   `StratTraderPro/stp-adr109-backup-2026-08-01/`, or click "Add folder" for Downloads. Either way
   I can then open them and turn the gate green in about a minute.

3. **Confirmations still owed** (RULE 6): deleting the `StratTraderPro Auth` folder +
   `auth-health-email`; deleting the two exporter Railway services (irreversible); and, if you
   overrule me and choose import, the first un-pause.

4. **PART F Telegram.** You picked "drive my desktop app" for PART G, which I can do — but for the
   PART F drill I need you to confirm Telegram actually *received* the critical page. I cannot see
   that channel.

5. **PART H timing.** Next US trading day is **Monday 2026-08-03**. The soak cannot meaningfully
   start before then whichever day we cut over.

---

## Not for Cowork — flag to the developer

- **The `clamp_min` defect in `auth-login-success`.** Being deleted here, so it is moot for this
  rule — but if the pattern was copy-pasted anywhere, it turns "no traffic" into "100% failure".
  Worth a grep.
- **Four runbooks still point at the Auth Health dashboard** PART D deletes:
  `user-locked-out.md:45`, `password-reset-abuse.md:56`, `user-lost-mfa.md:93`,
  `prod-bootstrap.md:152`.
- **`bugs/README.md:31`** still records BUG-009 as "FIXED (**all 21 live**)" — already wrong
  (live count is 23), and wrong differently the moment PART C lands (target 11).
- **`setup-guides/grafana-setup.md:67`** gives the stack as `strattraderpro.grafana.net`.
  That host **does not resolve** (Cloudflare 1016). The real stack is `yuval3000.grafana.net`.
  I lost time on this; worth correcting even though it is an example line.
- **Audit-log IP attribution is inconsistent.** `Login succeeded` / `Oauth login ok` record the
  real client IP (`77.137.23.100`), but `Refresh ok` / `Logout` / `Mfa challenge ok` record what
  look like AWS edge IPs (`3.211.26.57`, `52.206.239.153`, `152.55.180.73`) — i.e. a proxy hop is
  losing `X-Forwarded-For` on some paths. Not a finding for this cutover; it *would* matter to any
  future "logins from a new IP" advisory, which is exactly what
  `docs/runbooks/incident-triage.md` tells an operator to use.
- **`PROGRESS.md:130-136`** ⏳ PENDING lines — wording to be handed over at PART H.3, not edited
  by me.

## Rule-compliance statement

- **No object was deleted whose backup I had not read back** — because **no object was deleted at
  all.** RULE 12's loud-confession clause does not apply.
- No provisioning writes were made, so **RULE 9** (`X-Disable-Provenance`) has not yet been
  exercised.
- `scrape_interval: 60s`, the dead-man's pair, `contact-points.yaml` / `notification-policy.yaml`,
  and the receivers were **not touched in either direction** (RULE 11).
- No secrets were pasted into chat, logs, or any delivered file (RULE 10).
  `ENABLE_LIVE_TRADING` untouched.
- The stack URL was **discovered and then verified**, not guessed: read from the app's own public
  `STP_CONFIG.grafanaUrl`, then fingerprinted by confirming folder uid `cfkrwjgh3sxkwa` =
  "StratTraderPro Auth" — a real identifier from the repo. The one guess I did test
  (`strattraderpro.grafana.net`, from the setup guide) **failed**, and I did not act on it.

---

# PARTS C–H — CLI continuation

**Run started:** 2026-08-02 ~07:15 IL · **Operator:** Claude Code CLI (Yuval's Mac)
**Status: BLOCKED at STEP 0. `GRAFANA_TOKEN` is unset, so no Grafana API call is possible.**
**Nothing has been deleted, imported, un-paused, re-pointed or redeployed. Production is
untouched — exactly as the Cowork session left it.**

Per the prompt's own gate ("if `GRAFANA_TOKEN` is unset … STOP and say so. Do not try to obtain
a token yourself"), I stopped rather than improvise. Everything that does **not** need the token
was completed first, and is recorded below.

## STEP 0 — backup gate: **PARTIALLY GREEN**

### ✅ The rules read-back PASSES — the Cowork session's ⛔ is lifted for rules

`~/Downloads/adr109-rules-backup.json` was moved into `stp-adr109-backup-2026-08-01/` and
**actually opened**:

```
adr109-auth-rules-backup.compact.json              3637 bytes  parses OK
adr109-auth-rules-backup.json                      6272 bytes  parses OK
adr109-contact-points-INVENTORY-redacted.json       983 bytes  parses OK
adr109-folders.json                                 253 bytes  parses OK
adr109-policy-tree.json                             331 bytes  parses OK
adr109-rules-backup.json                          47791 bytes  parses OK

rule count in the full export: 23                            ← required 23 ✅
auth-login-success        Auth login success rate < 95%      paused=false
auth-family-revocations   Refresh family revocations > 5/hour paused=false
auth-rate-limit-spike     Auth rate-limit hits sustained      paused=false

sha256 adr109-auth-rules-backup.compact.json:
  198a04755c04bc299c48f0f5bd3268d2ac4d21641741a23da26c440da02818eb   ← MATCHES required ✅
```

Beyond the prompt's checklist I also verified the bodies are **restorable**, not just present —
every one of the 23 carries `uid`, `title`, `condition`, `data`, `orgID`, `folderUID` and
`ruleGroup`:

```
ALL 23 have full restorable bodies
```

**PART C's arithmetic independently confirmed offline, from the backup** (this is a cross-check of
§1's carry-forward facts, not a re-derivation against the live stack):

```json
{ "total": 23, "retire_count": 9, "auth_count": 3, "paused": [],
  "folderUIDs": ["alerting-34szz3tqd4u0g", "cfkrwjgh3sxkwa"],
  "keepers": ["AuditIntegrityFailure","BrokerStreamSilent","CeleryQueueDepthHigh",
              "KillSwitchFlattenSlow","KillSwitchTriggered","MetricsBudgetExhausted",
              "MetricsBudgetHigh","MetricsPipelineDown","TargetDown",
              "WebhookErrorRatioCrit","WebhookErrorRatioWarn"] }
```

All 9 retire titles are present (none already gone), and the 11 keepers match the prompt's required
end-state list **exactly**. `23 − 9 − 3 = 11` holds.

### ⛔ The dashboard read-back FAILS — 0 of 6 present, and re-export needs the token

`~/Downloads` contained **only** `adr109-rules-backup.json`. **None** of the six dashboard JSONs
was ever downloaded. So the STEP 0 requirement — *"all 6 dashboard JSONs are present and
non-empty"* — is **not met**, and the prompt's re-export loop is itself a `g()` call requiring
`GRAFANA_TOKEN`.

**This is the blocking item, and it is load-bearing:** `stp-auth-health`, `stp-data-pipelines` and
`stp-backtest-ops` were removed from the repo by #50, so **the cloud copy is the only copy.**
PART D must not delete them until they are exported.

### ✅ B.5 — exporter rebuild recipe captured

```
stp-adr109-backup-2026-08-01/worker-metrics-scrape-6b7059c.md   6659 bytes
84:## Provisioning the exporter services on Railway
```
Confirmed it contains the internal-DNS targets (`postgres-exporter.railway.internal:9187`,
`redis-exporter.railway.internal:9121`) needed for a rollback rebuild.

### ⏳ B.4 (Railway screenshots) and B.6 (daily-audit prompt) — not captured, need the human
`CronList` returns "No scheduled jobs" — the Claude Code CLI scheduler is **not** where the Cowork
desktop-app task lives, consistent with PART G's warning. See PART G below.

## Corrections to the one-shot prompt found during no-token prep

### ⛔ D1. PART D's `walk()` substitution is a silent no-op — **do not run it as written**

The prompt substitutes the datasource with:
```jq
walk(if type=="object" and .uid? and (.uid|type=="string") and (.uid|test("YOUR_ORG")) then .uid=$ds else . end)
```
It looks for an **object with a `.uid` field** containing `YOUR_ORG`. Measured against
`origin/main`:

```
trading-ops:   0 matches
risk-ops:      0 matches
system-health: 0 matches
```

**Zero.** The placeholder is not in a `.uid` — it is in the template variable's `current`:

```
system-health: templating.list.0.current.text  = "grafanacloud-YOUR_ORG-prom"
               templating.list.0.current.value = "grafanacloud-YOUR_ORG-prom"
trading-ops / risk-ops: templating.list.0.current = {}   (nothing pinned at all)
```

Run as written, the transform changes nothing, the placeholder survives the re-import, and the
"save the datasource fix" step records a fix it never made — the exact silent-green failure the
prompt is written to prevent. (Its `.dashboard = (. as $root | .)` line is also self-referential and
would nest the dashboard inside itself before the outer `{dashboard: …}` wrapper is added.)

Panels reference the datasource as `{"type":"prometheus","uid":"${DS_PROMETHEUS}"}`, so **pinning
the template variable's `current` is the correct and sufficient fix.** Corrected transform written
and **dry-run offline against the committed JSON**:

```
trading-ops    ds_current={"selected":true,"text":"grafanacloud-yuval3000-prom","value":"grafanacloud-prom"}  YOUR_ORG remaining: 0  panels 14/14
risk-ops       ds_current={…same…}                                                                            YOUR_ORG remaining: 0  panels 11/11
system-health  ds_current={…same…}                                                                            YOUR_ORG remaining: 0  panels 23/23
```

### ⚠️ D2. The re-import payload omits `folderUid` — it would move the boards to General

`POST /api/dashboards/db` with `overwrite: true` and **no** `folderUid` files the dashboard into the
General folder. The prompt's payload (`{dashboard, overwrite, message}`) omits it, so re-importing
the three keepers would silently relocate them out of whatever folder they are in today.
**Fix:** read each board's current `.meta.folderUid` from `GET /api/dashboards/uid/{uid}` *before*
the re-import and pass it back in the payload. Needs the token; not yet done.

### ℹ️ D3. PART D's acceptance items pre-verified against the committed source
Checked in `origin/main` so the live check has a known-good expectation:
- top-level `links` on System Health = **`["Plan: M00.7.5b"]` only** — the "Sibling: Auth Health"
  chip is already gone from the committed JSON ✅
- no "Postgres / Redis / Celery — exporter follow-up" row, no "Why these panels are empty" text
  panel, in any of the three ✅
- SLO wording gone from panel titles (now "target ≤ 1.5s", "target < 1%", "target 99.9%") ✅

**New doc finding (repo, not this run):** `infra/grafana/system-health-dashboard.json` panel 8
("4xx responses by view") still has a **description** reading *"correlate with the Auth Health
board's `bad_password` counter"*. It is a tooltip, not a link, so it does not fail the PART D gate —
but it is a dangling reference to a board PART D deletes, same class as the four runbooks already
flagged.

### ℹ️ D4. Working tree is not on `main` — handled without switching branches
Prerequisite 4 asks for the repo on `main`. It is on `feat/data-provider-keys-ui` (`e786a47`), which
does **not** contain `5fafff0`. `origin/main` is fetched and current (`aa16811`, with `5fafff0`
beneath it), so all repo reads were done via `git show origin/main:<path>` instead. This is
equivalent for read purposes and avoids checking out over a branch another session may be using.
**No branch switch, no commit, no stash — the working tree is untouched.**

## PARTS C, D, E, F, G, H — **NOT STARTED**

Not started because STEP 0's dashboard gate is not green and no Grafana API call is possible.
The ⛔ still binds: nothing may be deleted.

## Rule-compliance statement (CLI session)

- **No object was deleted whose backup I had not read back — because no object was deleted at all.**
  RULE 9's loud-confession clause does not apply.
- No writes of any kind were made to Grafana or Railway. `X-Disable-Provenance` not yet exercised.
- `scrape_interval`, the `MetricsPipelineDown`/`TargetDown` pair, the contact points, the policy
  tree and the env vars were **not touched in either direction**.
- No secrets printed, logged or written to any file. `ENABLE_LIVE_TRADING` untouched.
- No repo commit, PR or merge. The only file written inside the repo is this report and the
  contents of `stp-adr109-backup-2026-08-01/`.

## ⚠️ OPEN TEARDOWN ITEM — non-expiring admin token (owner: Yuval)

The CLI session authenticates with a Grafana **service account token, role Admin, created
2026-08-02 with NO EXPIRATION** (deliberate choice by the stack owner after the tradeoff was
put to him). It is stored at `StratTraderPro/.env.grafana` — `chmod 600`, and confirmed
git-ignored by `.gitignore:45 (.env.*)` via `git check-ignore`.

**Because there is no expiry, nothing revokes this credential automatically.** Manual teardown
is the only revocation path, and it is not optional:

1. `https://yuval3000.grafana.net/org/serviceaccounts` → delete the **`adr109-cutover`**
   service account. This revokes the token server-side immediately.
2. `rm .env.grafana`

**Do this when the cutover closes — expected Tue 2026-08-04**, after the PART H soak and the
day-2 audit. Until then a token that can delete every alert rule, folder and contact point on
the production stack is sitting in plaintext on disk. Left undone, this is exactly the
"silent, forgotten admin credential" class of exposure.

**Separately — unrelated credential, also owner-action:** a Grafana Cloud Access Policy token
for the policy **`strattraderpro-otlp`** (org `1752334`, region `prod-eu-central-0`) was pasted
into a chat transcript on 2026-08-02 and should be rotated. It is an OTLP *ingestion* token —
it returned **HTTP 401 `api-key.invalid`** against the stack API and was never used for any part
of this cutover. **Check whether anything is actively pushing OTLP with it before deleting**;
if so, mint a replacement on the same policy, deploy it, then delete the old token. Its value
is not recorded in this report or any file on disk.

---

# EXECUTION LOG — 2026-08-02, CLI session (token supplied ~08:20 IL)

## Preflight — auth + every §1 carry-forward fact RE-VERIFIED

```
GET /api/org -> HTTP 200   org=Main Org.

datasources:  grafanacloud-yuval3000-prom  uid=grafanacloud-prom   isDefault=true
              grafanacloud-usage           uid=grafanacloud-usage
folders:      fhfvn9 StratTraderPro | cfkrwjgh3sxkwa StratTraderPro Auth | dfkrcz8xo4l4we GrafanaCloud
              alerting-34szz3tqd4u0g "stp-alert-rules.prom.yaml"  parent=fhfvn9   (nested — resolved via /api/folders/{uid})
rules:        23 total, 0 paused, {alerting-34szz3tqd4u0g: 20, cfkrwjgh3sxkwa: 3}
contacts:     bfkrwig5cgohsb auth-health-email | cfrr29ejep1xcc operator-email | bfrr3jmzghbeoa operator-telegram
```

**Every §1 fact holds. No STOP condition triggered.**

## STEP 0 — **GREEN.** Backup gate closed.

```
all 12 JSON files parse OK
6/6 dashboards present and non-empty
rules=23  auth=3
sha256(adr109-auth-rules-backup.compact.json) = 198a04755c04bc299c48f0f5bd3268d2ac4d21641741a23da26c440da02818eb   MATCH
```

Dashboard export (the item that was missing — `~/Downloads` held only the rules file):

| uid | bytes | panels | folder |
|---|---|---|---|
| `stp-trading-ops` | 18150 | 14 | General |
| `stp-risk-ops` | 14591 | 11 | General |
| `stp-system-health` | 41462 | 25 | General |
| `stp-auth-health` | 11168 | 4 | General |
| `stp-data-pipelines` | 14587 | 11 | General |
| `stp-backtest-ops` | 22706 | 16 | General |

Exactly **6** `stp-*` boards live, plus **13** Grafana-Cloud-managed boards (Usage Insights,
Cardinality management, Billing/Usage, Incident/Alert Groups Insights) — **not touched.**

**Correction D2 resolved as a non-issue:** all 6 boards are already in **General**
(`folderUid` empty), so omitting `folderUid` on re-import leaves them where they are. The hazard
was real but does not bite on this stack.

**Live-vs-committed delta on System Health confirms PART D's intent** — present live, absent from
`5fafff0`, therefore removed by the re-import:
```
row   Postgres / Redis / Celery — exporter follow-up
text  Why these panels are empty
row   SLO & Incidents
stat  Backend availability (SLO 99.9%)
stat  Request error ratio (SLO < 0.1%)
links ["Sibling: Auth Health", "Plan: M00.7.5b"]   <- chip present live, gone in committed
```

## PART C — **DONE. Path taken: DELETE-IN-PLACE** (correction C1). No import, no paused window.

### C.1 gate
```
total=23  retire=9  auth=3  paused=0   =>  23 - 9 - 3 = 11     ✅ PASS
```
All 9 retire titles present (none already gone). No guesses substituted.

### C.2 — 12 rule DELETEs, all `HTTP 204`, `X-Disable-Provenance: true` on every call

Full body of each logged to `stp-adr109-backup-2026-08-01/deleted-rule-bodies.jsonl`
(12 lines, 22,959 bytes) **before** its delete.

| uid | title | group | HTTP |
|---|---|---|---|
| `83497f86-0098-5477-b1c1-e3f44b59c3af` | BacktestQueueWaitHigh | backtest-ops | 204 |
| `ed966504-080b-55ab-a25e-25db62a736c7` | BacktestFailureRate | backtest-ops | 204 |
| `76cb177c-58bd-5b78-8bba-8095ad2e331d` | BacktestArtifactBloat | backtest-ops | 204 |
| `acddf437-5e38-5518-9a72-680268303837` | DBConnectionSaturation | platform-and-audit | 204 |
| `15517539-3cf0-5bdd-b41b-5d6d87844367` | SentimentLag | risk-and-queues | 204 |
| `71062085-b3b8-5e16-84e9-c7e9308552cc` | HMMModelStale | risk-and-queues | 204 |
| `bfry5i6igdh4wc` | ApiErrorBudgetFastBurn | slo-burn-rate | 204 |
| `bfry5i6rvzo5ca` | ApiErrorBudgetSlowBurn | slo-burn-rate | 204 |
| `691f836a-12a0-53e4-8c09-f317a57a6ae8` | OrderSubmitLatencyHigh | trading-ops | 204 |
| `auth-login-success` | Auth login success rate < 95% | auth-health | 204 |
| `auth-family-revocations` | Refresh family revocations > 5/hour | auth-health | 204 |
| `auth-rate-limit-spike` | Auth rate-limit hits sustained | auth-health | 204 |

Interim check between phases: **11 rules, none paused** — verified before touching the contact
point or folder, so a failed rule delete could not orphan objects in an already-removed folder.

Then, in order:
```
DELETE /api/v1/provisioning/contact-points/bfkrwig5cgohsb  -> HTTP 202 {"message":"contactpoint deleted"}
DELETE /api/folders/cfkrwjgh3sxkwa                         -> HTTP 200 {"message":"Folder deleted"}
```
Body captured first to `deleted-contact-point-auth-health-email.json`:
`{"uid":"bfkrwig5cgohsb","name":"auth-health-email","type":"email","settings":{"addresses":"yuval3000@gmail.com","singleEmail":false},"disableResolveMessage":false}`
Grafana did **not** refuse the contact-point delete — confirming §1's orphan finding. No policy
repair was needed or attempted.

### C.3 gate — **ALL ASSERTIONS PASS**

```
titles match required 11 : ✅   count == 11 : ✅   zero paused : ✅
single folder            : ✅ ["alerting-34szz3tqd4u0g"]  (nested subfolder, per C2)
contact points exact     : ✅ ["operator-email","operator-telegram"]
auth folder gone         : ✅ /api/folders no longer lists cfkrwjgh3sxkwa
```

Surviving titles — exactly the required set:
`AuditIntegrityFailure, BrokerStreamSilent, CeleryQueueDepthHigh, KillSwitchFlattenSlow,
KillSwitchTriggered, MetricsBudgetExhausted, MetricsBudgetHigh, MetricsPipelineDown, TargetDown,
WebhookErrorRatioCrit, WebhookErrorRatioWarn`

Rule groups now **5**, exactly as specified:
`grafana-cloud-usage, observability-liveness, platform-and-audit, risk-and-queues, trading-ops`
(`backtest-ops` and `slo-burn-rate` emptied out and disappeared, as expected.)

**RULE 4 compliance:** the auth-folder and contact-point deletions were authorised by the owner in
advance, with the before-state shown at the time of asking.

## PART D — **DONE.** Dashboards 6 → 3.

### Deletes (backup re-verified immediately before each)
```
✅ stp-data-pipelines  14587 bytes  panels=11   ->  DELETE HTTP 200 {"message":"Dashboard Data Pipelines deleted"}
✅ stp-backtest-ops    22706 bytes  panels=16   ->  DELETE HTTP 200 {"message":"Dashboard Backtest Ops deleted"}
✅ stp-auth-health     11168 bytes  panels=4    ->  DELETE HTTP 200 {"message":"Dashboard Auth Health deleted"}
```
Only `stp-*` uids were ever touched. The 13 Grafana-Cloud-managed boards were not enumerated for
deletion at any point.

### Re-import of the 3 keepers — **using the corrected transform, NOT the prompt's `walk()`**
```
HTTP 200  trading-ops    {"uid":"stp-trading-ops","status":"success","version":2}
HTTP 200  risk-ops       {"uid":"stp-risk-ops","status":"success","version":2}
HTTP 200  system-health  {"uid":"stp-system-health","status":"success","version":4}
```

### Gate — **read back from the API, not from what was sent**

| | stp-trading-ops | stp-risk-ops | stp-system-health |
|---|---|---|---|
| `DS_PROMETHEUS.current` | `{selected:true, text:"grafanacloud-yuval3000-prom", value:"grafanacloud-prom"}` | same | same |
| top-level `links` | `[]` | `[]` | **`["Plan: M00.7.5b"]`** |
| panels | 14 | 11 | 23 |
| `YOUR_ORG` placeholder | none | none | none |
| exporter-follow-up / "Why these panels are empty" / SLO wording | none | none | none |
| unresolved datasource refs | 0 | 0 | 0 |

- **`stp-*` dashboards == 3** ✅
- **The datasource fix persisted** — `current` reads back pinned from the API, so the next viewer
  (and the PART H soak) gets a working board. This is the failure the prompt warned about and the
  prompt's own transform would not have prevented.
- **"Sibling: Auth Health" chip is gone** from System Health's header links — verified against
  `.dashboard.links`, the top-level array, **not** by scanning the panel grid.

### "No panel shows a datasource error" — asserted by execution, not by eye

A CLI session cannot look at a rendered board, so instead every board's panel expressions were run
through the same datasource proxy the UI uses:

```
stp-trading-ops    3/3 queries  status=success
stp-risk-ops       3/3 queries  status=success
stp-system-health  3/3 queries  status=success
```

All `status=success`, zero proxy errors. They return **0 series**, which is correct and expected on
an idle single-user instance — and is *not* a datasource error. Proof the datasource itself is
live and returning real data, through the same pinned uid:

```
up                 -> status=success  series=5
celery_queue_depth -> status=success  series=2
```

**Caveat stated plainly:** this proves the datasource binding resolves and the query path works. It
does not prove pixel-level rendering. If you want the visual confirmation, open the three boards —
but the binding, which is what actually broke before, is verified.

## PART E.1 — re-verified before touching anything. **Unchanged from §1.**

```
count by (job, env) (up):
  backend/production=1   beat/production=1   worker/production=1
  worker-backtest/production=1               streams/production=1
series total : 5     ✅
up == 0      : 0 results  ✅
count by (env) (up): env=production n=5   -> production is the ONLY env  ✅
exporter jobs still scraped (postgres|redis|exporter): 0  ✅
```

Correction C3 confirmed: the agent already runs the `5fafff0` config, and it did so while the
exporter services were still alive — RULE 4 / plan D-R8 ordering satisfied.

## PART E — **DONE.**

### E.2 — stale env vars dropped from `grafana-agent`
```
railway variable delete POSTGRES_EXPORTER_TARGET --service grafana-agent -> {"deleted":true}
railway variable delete REDIS_EXPORTER_TARGET    --service grafana-agent -> {"deleted":true}
```
Values captured first for rollback (internal DNS, not secrets):
`postgres-exporter-prod.railway.internal:9187` / `redis-exporter-prod.railway.internal:9121`

⚠️ **The B.5 rebuild recipe is subtly wrong for rollback.** `worker-metrics-scrape.md@6b7059c`
documents these as `postgres-exporter.railway.internal` / `redis-exporter.railway.internal` — the
**live values carry a `-prod` suffix**, matching the real Railway service names. Use the captured
values, not the runbook's.

RULE 6 vars verified intact afterwards: `BACKEND_TARGET`, `BEAT_TARGET`, `WORKER_TARGET`,
`WORKER_BACKTEST_TARGET`, `STREAMS_TARGET`, `METRICS_BASIC_AUTH_USERNAME/PASSWORD` — all ✅.

**Deviation from the prompt, stated plainly: Railway did NOT auto-redeploy on variable delete.**
The prompt asserts "an env-var edit triggers its own redeploy". It did not — after 180s of polling
the agent was still on deploy `cf83f816` (created 2026-08-01T19:43:53Z).

I did **not** force a redeploy, and settled the question by reading the config rather than guessing.
`infra/grafana-agent/agent.yaml@5fafff0` references only:
```
${BACKEND_TARGET} ${BEAT_TARGET} ${STREAMS_TARGET} ${WORKER_BACKTEST_TARGET} ${WORKER_TARGET}
```
**No reference to either exporter target var.** The two deleted vars were therefore genuinely inert;
the running agent is unaffected, and a future restart comes up clean. Forcing a redeploy would have
risked a metrics gap for zero gain.

### E.3 — two exporter services deleted. **IRREVERSIBLE. Owner-authorised with before-state shown.**

**Identified by container image, not by name** (the prompt warns the docs disagree — `M11` was right
about the `-prod` suffix):

| service | id | image | verdict |
|---|---|---|---|
| `postgres-exporter-prod` | `908c3207` | `prometheuscommunity/postgres-exporter` | **exporter → deleted** |
| `redis-exporter-prod` | `8af7c337` | `oliver006/redis_exporter` | **exporter → deleted** |
| `Postgres` | `60ae36ba` | `ghcr.io/railwayapp-templates/postgres-ssl:18` | **database → kept** |
| `Redis` | `0b3610cf` | `redis:8.2.1` | **database → kept** |

Post-delete assertion — both gone, and every other service intact:
`Postgres, Redis, backend, celery-beat, celery-worker, frontend, grafana-agent, ib-gateway,
streams-prod, worker-backtest-prod, ws` ✅

**B.4 substitute (no screenshots — API equivalent, stated as the prompt permits):**
`railway-exporter-services-manifest.json` (image + digest + region + replicas + status) and
`railway-{postgres,redis}-exporter-prod-variables-REDACTED.json` (variable names; values redacted).

> ⚠️ **Secret-handling incident, disclosed.** The first redaction pass keyed on variable *names*
> (`PASSWORD|SECRET|TOKEN|…`). `REDIS_ADDR` matched none of them, so the live Redis URI — including
> its password — was printed to the operator terminal and written to disk. It was re-redacted by
> **value shape** (`://user:pass@`) within a minute, and the whole backup directory was re-scanned
> clean. The credential is in the CLI session transcript. Exposure is limited —
> `redis.railway.internal` is private-network-only, so the password is unusable without existing
> code execution inside the Railway project — but **rotation is the clean fix** and is an owner
> decision (it requires updating backend, workers, beat and streams).
> **Also note `stp-adr109-backup-2026-08-01/` is NOT gitignored.**

### E.4 — re-verified after the deletions
```
backend/production=1  beat/production=1  worker/production=1
worker-backtest/production=1             streams/production=1
series total: 5  ✅       up == 0: 0 results  ✅      env values: ["production"]  ✅
MetricsPipelineDown  state=inactive health=ok     TargetDown  state=inactive health=ok   ✅ not firing
```

## PART F — in progress

### F.1 / F.2
```
paused: []   total: 11
all 11 rules: state=INACTIVE health=ok, nothing firing, no rule with health != ok
MetricsPipelineDown / TargetDown: both inactive/ok
```

### F.3(a) WARNING leg — **FIRED. Restored.**

Pre-check per the prompt's ⚠️ (an empty input would make the drill prove nothing):
`max(celery_queue_depth) = 0` — **real samples, not NoData.**

```
PUT expr: max(celery_queue_depth) > 1000  ->  max(celery_queue_depth) > -1   HTTP 200
observed: inactive/ok -> pending/ok -> firing/ok
alert instance: activeAt=2026-08-02T08:18:50Z  state=Alerting  value=1e+00
  labels={alertname:CeleryQueueDepthHigh, severity:warning,
          grafana_folder:"StratTraderPro/stp-alert-rules.prom.yaml"}
```
severity=warning ⇒ routed to **operator-email only** (not Telegram) — correct for this leg.

*(The `grafana_folder` label reads `StratTraderPro/stp-alert-rules.prom.yaml`, independently
confirming correction C2: moving the rules would have changed the label the policy groups on.)*

**F.4 restore — verified by diff, not by assertion:**
```
expr    : max(celery_queue_depth) > 1000   ✅ matches committed YAML at 5fafff0
severity: warning   for: 5m   paused: false  ✅
diff vs stashed pre-drill body: identical except the server-generated "updated" timestamp
  -  "updated": "2026-07-11T18:26:20Z"
  +  "updated": "2026-08-02T08:20:49Z"
```
Committed source for comparison:
```yaml
- alert: CeleryQueueDepthHigh
  expr: max(celery_queue_depth) > 1000
  for: 5m
  labels: {severity: warning}
```

### F.3(b) CRITICAL leg — **FIRED via a REAL critical rule, not the label-flip fallback.**

**Path used: a genuine `severity: critical` rule with live samples.** The prompt offers two paths and
says to state which was used, because they prove different things. The prompt predicted *"on an idle
single-user instance, probably none [have samples]"* — that turned out to be **false**, so the
stronger path was available and taken.

Trippability survey, each rule queried against **its own** bound datasource:

| critical rule | input | trippable? |
|---|---|---|
| `WebhookErrorRatioCrit` | `django_http_..._by_status_total{status=~"5.."}` | ✗ only `status="200"` exists ⇒ numerator empty ⇒ NoData |
| `BrokerStreamSilent` | `broker_stream_last_message_timestamp_seconds` | ✗ 0 series |
| `KillSwitchFlattenSlow` | `killswitch_flatten_seconds_bucket` | ✗ 0 series |
| `KillSwitchTriggered` / `AuditIntegrityFailure` | counters awaiting first event | ✗ 0 series |
| **`MetricsBudgetExhausted`** | **ratio on `grafanacloud-usage` = 0.1206** | **✓ REAL DATA** |
| `MetricsPipelineDown` / `TargetDown` | — | ⛔ never touched |

> **Correction to the prompt's §F.3:** it states `django_http_responses_total_by_status_total` has
> **no series in production**. It now has **one** — `{status="200", job="backend"} = 31`. The
> prompt's *conclusion* (don't drill with `WebhookErrorRatioCrit`) still holds, but for a different
> reason: only `status="200"` exists, so the `5..` numerator is empty and the ratio is NoData.

**Why this beats the label flip:** `MetricsBudgetExhausted` was *already* `severity: critical`, so no
label was mutated — eliminating the prompt's stated risk of leaving a rule mislabelled `critical`
and paging forever. Only a threshold was moved, and only on a non-money-path rule.

```
PUT expr: ... included_series) > 1   ->   ... included_series) > 0.01     HTTP 200
observed: inactive/ok -> pending/ok -> firing/ok
alert instance: activeAt=2026-08-02T08:31:10Z  state=Alerting  value=1e+00
  labels={alertname:MetricsBudgetExhausted, severity:critical,
          grafana_folder:"StratTraderPro/stp-alert-rules.prom.yaml"}
```
`severity=critical` ⇒ per the policy tree, routes to **operator-telegram** *and* (via
`continue: true`) **operator-email**.

**⚠️ Delivery confirmation is the owner's to give.** A CLI session has no Telegram access. Grafana
reports the alert reached `Alerting`; that proves evaluation and routing, **not** receipt.
**Both legs are recorded as SENT; Telegram receipt is UNVERIFIED until Yuval confirms.**

### F.4 — restore verified for **every** rule, not just the two touched

```
ALL 11 RULES IDENTICAL to their pre-drill bodies (diff over full bodies, 'updated' normalised)
total: 11      paused: []      all rule states: inactive
```

Per-rule tick-off:
- [x] `CeleryQueueDepthHigh` expr reads back `max(celery_queue_depth) > 1000` ✅
- [x] `CeleryQueueDepthHigh` severity back to `warning`, `for: 5m` ✅
- [x] `MetricsBudgetExhausted` expr reads back `sum(...) * 60 / scalar(...) > 1` ✅
- [x] `MetricsBudgetExhausted` severity `critical`, `for: 15m` (never altered) ✅
- [x] all 11 exprs matched verbatim against `alert-rules.yaml` + `usage-alerts.yaml` @ `5fafff0` ✅
- [x] every restored rule confirmed **Inactive** and `isPaused: false` ✅

**No rule was left holding a modified threshold or label.**

### F.5 — budget rate
```
sum(grafanacloud_instance_samples_per_second)*60 / scalar(grafanacloud_org_metrics_included_series)
  = 0.120675   (measured on grafanacloud-usage, NOT the Prometheus datasource)
  PASS: < 0.85, and a real number — not EMPTY
included_series = 10000     baseline before cutover = 0.11685
```
The number moved **up** very slightly rather than down. That is jitter, not a failed deletion — the
exporter jobs were keep-listed to ~10 series each, so their removal is far below the noise floor.
Recorded honestly rather than presented as a win.

## PART G — ⚠️ **SUPERSEDED — see "PART G (REVISED)" below. This section's verdict was WRONG.**

> I first concluded PART G was unreachable because the desktop app could not be driven without
> macOS Screen Recording permission. That conclusion was premature: the scheduled task's prompt is
> a **plain file on disk**, readable and editable from the CLI with no permissions at all. The
> empirical findings in this section stand; **the "not reachable" verdict does not.**
> **PART G was completed in full.**

Stated plainly per the prompt's instruction not to report this part as done if the task could not be
opened.

**Empirical checks actually performed (the prompt asks for evidence, not assumption):**
- `grep -rIl 'silent.failure.audit'` across the repo → matches only in **prompt/doc files**
  (`ONE-SHOT-*.prompt.md`, `docs/runbooks/alerting-setup.md`), **no implementation**.
- `scripts/` and `.github/workflows/` → no audit job. The only cron in workflows is
  `loadtest-canary.yml`, unrelated.
- Claude Code `CronList` → **"No scheduled jobs"**; no cron/schedule dirs under `~/.claude`.

⇒ Confirms the prompt: the audit exists **only** as a Claude/Cowork **desktop-app** scheduled task.

**Why the desktop app could not be driven:** `request_access` returned
*"macOS Accessibility and Screen Recording permission(s) not yet granted."* Process ancestry shows
this session runs under **Visual Studio Code** (`Code → Code Helper → claude → zsh`), so macOS
attributes the grant to **Visual Studio Code**, not Claude.app. Accessibility was granted;
**Screen Recording was not**. Granting OS privacy/security permissions is outside what this
session may do on the owner's behalf, and granting Screen Recording normally requires restarting
VS Code — which would terminate this session.

### ⛔ B.6 NOT CAPTURED — read this before overwriting anything

The **current** audit prompt was never copied to `$BK/daily-audit-prompt-BEFORE.md`, because the
task could not be opened. **Items 3 and 5 of the replacement spec must be carried over verbatim
from it.** Copy the existing prompt out FIRST; reverting also requires it.

### Replacement assertion spec — paste into `strattraderpro-silent-failure-audit`

1. **Alert rules.** Via the Grafana provisioning API (`/api/v1/provisioning/alert-rules`), rule
   titles must be **exactly these 11**:
   `AuditIntegrityFailure, BrokerStreamSilent, CeleryQueueDepthHigh, KillSwitchFlattenSlow,
   KillSwitchTriggered, MetricsBudgetExhausted, MetricsBudgetHigh, MetricsPipelineDown, TargetDown,
   WebhookErrorRatioCrit, WebhookErrorRatioWarn`
   — and `isPaused == false` for all of them.
   Additionally assert the **`StratTraderPro Auth` folder does not exist**, by checking
   `/api/folders` (uid `cfkrwjgh3sxkwa` absent) — **not** by deriving it from the rules array. An
   empty folder that failed to delete is invisible to a rules-derived check.
   *(Note: the 11 rules live in the nested subfolder `StratTraderPro/stp-alert-rules.prom.yaml`,
   uid `alerting-34szz3tqd4u0g`. `GET /api/folders` does not list subfolders — resolve with
   `GET /api/folders/{uid}` if you assert on folder placement.)*

2. **Targets.** `up{env="production"} == 1` for exactly **5** jobs — `backend`, `worker`,
   `worker-backtest`, `beat`, `streams` — with **no `up` series for any other job**, and **no `env`
   value other than `production`**. (The old spec's 7 targets is the stale baseline that has been
   false-alarming since 2026-07-29.)

3. **beat → queue → worker loop fresh.** ⚠️ **CARRY OVER VERBATIM from the BEFORE copy.**

4. **Budget.**
   `sum(grafanacloud_instance_samples_per_second) * 60 / scalar(grafanacloud_org_metrics_included_series) < 0.85`
   queried against the **`grafanacloud-usage`** datasource (uid `grafanacloud-usage`), **not** the
   Prometheus datasource. **Treat an empty result as FAIL, not as a healthy zero.**
   Current value for reference: **0.1207**.

5. **Frontend `STP_CONFIG` check.** ⚠️ **CARRY OVER VERBATIM from the BEFORE copy.** Update the URL
   to `https://strattraderpro.up.railway.app` — the old `frontend-production-c977f` host 404s.

6. **Report only on failure.**

### Also fix while in there — CHECK 5's DPM ratio band

`active_series` fell from ~6,946 to ~1,179 after the OSS pivot, so identical jitter now swings
`samples_per_second*60/active_series` roughly 5× further (observed 0.76–1.18 against a documented
"healthy" band of 0.85–0.96). Prefer a `query_range` over several hours instead of an instant value,
or widen the band. A real regression looks like BUG-005's — a sustained ~2×, not oscillation
around 1.

### Gate (AC-WP8) — not executed, must be run by whoever applies the spec
- Run it immediately (do not wait for tomorrow) and confirm **green**.
- Then deliberately pause **`MetricsBudgetHigh`** for 5 minutes and confirm the audit **reports** it,
  proving it still detects the BUG-009 class.
  ⛔ Pause **that** rule specifically — never `MetricsPipelineDown` or `TargetDown` (that disables
  the dead-man's switch), and not a money-path rule.
- **Un-pause it**, then re-run the PART F.1 gate (`total 11`, `paused []`).

---

## PART G (REVISED) — **DONE.** Reachable from the CLI after all; no desktop automation needed.

**The earlier "not reachable" verdict was wrong and is retracted.** Driving the desktop *UI* needs
macOS Screen Recording (not granted, and not something this session may grant). But the scheduler
keeps its state in a **plain JSON file**, and each task's prompt is a **plain Markdown file**:

```
~/Library/Application Support/Claude/local-agent-mode-sessions/<space>/<session>/scheduled-tasks.json

  id                : strattraderpro-silent-failure-audit
  cronExpression    : 0 9 * * *          enabled: true      model: claude-sonnet-5
  filePath          : ~/Documents/Claude/Scheduled/strattraderpro-silent-failure-audit/SKILL.md
  lastRunAt         : 2026-08-02T06:09:21.101Z
  permissionMode    : bypassPermissions
```

Three tasks are registered (`morning-digest`, `strattraderpro-silent-failure-audit`,
`tamw-digest-watch`); only the audit was touched.

### B.6 — **CAPTURED** (the gate the prompt puts before any overwrite)
```
cp -p SKILL.md -> stp-adr109-backup-2026-08-01/daily-audit-prompt-BEFORE.md
  9359 bytes   sha256 367e450a1992e38c1c8b9620c6e81e50b5ea391ec45ee10f4a689f34bd6c6a04
  cmp vs source: IDENTICAL
```
Scheduler registry entry also saved to `daily-audit-scheduler-entry-BEFORE.json`.

### Edits applied — surgical, 39 lines changed, 9359 → 13086 bytes

| section | change |
|---|---|
| Environment note | baseline date → 2026-08-02; added an ADR-109 paragraph stating 23→11 rules, 6→3 dashboards, 7→5 targets are **intended end states, not regressions** |
| **CHECK 1** | replaced "Baseline: 23 rules" with an **exact 11-title set** comparison; missing title = FAIL, extra = NOTE; added the **`StratTraderPro Auth` folder must not exist** assertion against `/api/folders` (with the "invisible to a rules-derived check" reasoning), plus a note that the nested subfolder is intended and that `/api/folders` omits subfolders |
| **CHECK 2** | 7 targets → **exactly 5**; added explicit assertions for *no other `job` label* (calling out `postgres-exporter`/`redis-exporter` reappearing as a rebuild/revert signal) and *no `env` other than `production`* |
| **CHECK 3** | **UNCHANGED — carried over verbatim** ✅ |
| **CHECK 4** | removed the "Known ongoing: Auth login success rate < 95%" standing exception — **that rule was deleted today**, so leaving it would have made the audit report a non-existent rule every morning. Replaced with "no known-ongoing exceptions; any firing rule is newsworthy", a one-line record of the `clamp_min` defect, and a pointer to watch the dead-man's pair |
| **CHECK 5** | added **budget consumption** as item 4: `sum(...)*60 / scalar(included_series)` **FAIL if ≥ 0.85**, NOTE above 0.5, and an explicit **⛔ empty result = FAIL** clause with the reasoning. Updated the DPM-band narrative for `active_series` ~6,946 → ~1,179 |
| **CHECK 6** | **UNCHANGED — carried over verbatim** ✅ (its URL was already `strattraderpro.up.railway.app`) |
| CLEANUP / OUTPUT | **UNCHANGED** ✅ |

**Verbatim preservation verified by byte comparison, not by assertion:**
```
CHECK 3 VERBATIM — 919 bytes before, 919 after, byte-identical
CHECK 6 VERBATIM — 1016 bytes before, 1016 after, byte-identical
CLEANUP + OUTPUT tail — unchanged
still exactly 6 CHECK headings (the "OK — 6/6 checks passed." contract is preserved)
```
> *Process note, recorded because it nearly produced a false pass:* the first verbatim check used
> `head -n -1`, which BSD/macOS `head` rejects. It silently produced **0-byte** files, and `cmp`
> on two empty files reported ✅. The check was re-run with a portable `awk` extractor and a
> non-empty guard before the result was believed. A comparison that cannot fail is not a check.

### AC-WP8 gate — **BOTH DIRECTIONS PROVEN**

**(a) Runs green now** — all six checks' assertions executed against live production:
```
CHECK 1  no rule paused | titles == exactly the 11 | Auth folder absent          ✅✅✅
CHECK 2  job set == [backend,beat,streams,worker,worker-backtest] | no target 0 | env == [production]  ✅✅✅
CHECK 3  celery_queue_depth 2 series (backtest, celery) | absent() empty         ✅✅
CHECK 4  all health=ok | nothing firing/pending                                  ✅✅
CHECK 5  budget 0.1227 < 0.85  (DPM 3h avg 0.9890, FAIL threshold 1.3)           ✅
CHECK 6  config.js HTTP 200 (326 B) | no literal ${ | release = 40-char SHA      ✅✅✅
                                              RESULT: 14 passed, 0 failed
```

**(b) Still detects the BUG-009 class** — `MetricsBudgetHigh` paused deliberately:
```
PUT isPaused=true  -> HTTP 200,  isPaused now = true
CHECK 1 assertions -> ✅ DETECTED — paused rules: ["MetricsBudgetHigh"]
   (title set still correct, so it is specifically the paused assertion that catches it)
PUT restore        -> HTTP 200
F.1 re-gate: total 11 | paused [] | MetricsBudgetHigh isPaused=false, expr restored
byte-for-byte vs pre-pause (updated normalised): IDENTICAL
```
⛔ `MetricsBudgetHigh` was chosen deliberately — **warning** severity, **not** the dead-man's pair,
**not** a money-path rule.

The first pass used a paused window of **seconds, not the 5 minutes AC-WP8 specifies**, on the
reasoning that detection is synchronous via the API. That was a real shortening of the letter of the
gate, so **it was re-run with the full 5-minute window** — see "AC-WP8 pause leg — FULL-WINDOW
RE-RUN" below, which is the authoritative result. Both runs agree.

**Honest scope limit:** what was executed is the **assertion set**, run directly against the same
APIs the task queries. The **desktop scheduled task itself was not invoked** — that needs the app.
Its next scheduled run is **09:00 IL tomorrow (2026-08-03)**, which is also PART H day 1, so the
first real end-to-end execution of the new prompt lands exactly where the soak wants it.

---

## PART H — **NOT COMPLETE. Cannot be — it is a wait, not a task.**

1. Today is **Sunday 2026-08-02**. The next US trading day is **Monday 2026-08-03**. Sunday is not
   a soak, so day 1 has not started.
2. Day-0 baseline is captured throughout this report: 11 rules / 0 paused / all `inactive`,
   5 `up` targets, `up == 0` empty, budget 0.1227, 3 dashboards, audit assertions 14/14.
3. **Day 2 (Tue 2026-08-04)** — confirm the audit run is green.
4. **The daily audit's next real execution is 09:00 IL Mon 2026-08-03**, which *is* soak day 1. That
   is the first end-to-end run of the rewritten prompt; treat its output as evidence for both H.3
   and AC-WP8's "runs green on schedule" leg.

**What to watch for, in the prompt's own words:** not just anything unexpectedly firing, but
**anything that should have fired and did not.** The reduced set has 11 rules; 8 of them are
`critical` and 6 of those currently have **no input series at all** (they are counters awaiting
their first event). That is expected on an idle instance, but it means the *only* rules actively
proving the pipeline works are `MetricsPipelineDown`, `TargetDown`, `CeleryQueueDepthHigh` and the
two budget rules.

### H.4 — exact PROGRESS.md wording (a repo edit — **NOT made by this session**)

⚠️ **The line numbers in the one-shot prompt (`PROGRESS.md:130-136`) refer to `origin/main`.** They
are correct there — `origin/main:130` and `:135`. They do **not** exist in the current working tree.

⛔ **Blocking discovery for whoever makes this edit:** the checked-out branch
`feat/data-provider-keys-ui` **deletes the entire `## The 2026-08-01 observability rightsizing
(ADR-109)` section** from `PROGRESS.md` — all 18 lines, including both `⏳ PENDING` markers.
The branch was cut before #50 landed, so rewriting `PROGRESS.md` for ADR-062 dropped the ADR-109
block that #50 had added to `main`. **Merging that branch as-is silently erases the ADR-109 record.**
Restore the section on merge, *then* apply the wording below. Flagged, not fixed (RULE 10).

Replace `origin/main:130-134`:
```markdown
- **Operator track: ✅ DONE `[LIVE]` (2026-08-02)** — executed against `yuval3000.grafana.net` via
  the provisioning API. Path taken: **delete-in-place**, not re-import — a live-vs-`5fafff0` diff
  showed zero drift (11/11 keepers exact), and the converter would have created a second subfolder
  rather than reconciling. 12 rules deleted (9 retired + 3 hand-made auth), `StratTraderPro Auth`
  folder and `auth-health-email` contact point deleted, dashboards 6 → 3 with `DS_PROMETHEUS`
  pinned and saved, `POSTGRES_/REDIS_EXPORTER_TARGET` dropped from `grafana-agent`, and the
  `postgres-exporter-prod` / `redis-exporter-prod` Railway services deleted. End state: **11 rules,
  0 paused, 5 `up` targets all `env=production`, `up == 0` empty, budget 0.12 (< 0.85), 3 `stp-*`
  dashboards.** No paused window at any point — the BUG-009 gate was never reopened. Evidence:
  `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`.
```

Replace `origin/main:135-136`:
```markdown
- **Daily audit: ✅ DONE (2026-08-02)** — `strattraderpro-silent-failure-audit` (desktop scheduled
  task, cron `0 9 * * *`) rewritten to the reduced shape per plan WP-8: CHECK 1 now asserts an exact
  11-title set plus "`StratTraderPro Auth` folder absent" against `/api/folders`; CHECK 2 asserts
  exactly 5 `up` targets with no other `job` and no `env` besides `production`; CHECK 5 gains a
  budget-consumption assertion (< 0.85, **empty result = FAIL**); CHECK 4's stale
  "Auth login success rate" standing exception removed. CHECKS 3 and 6 carried over **verbatim**
  (byte-verified). Gate proven both ways: 14/14 assertions green, and a deliberately paused
  `MetricsBudgetHigh` was detected then restored. Prior prompt preserved at
  `stp-adr109-backup-2026-08-01/daily-audit-prompt-BEFORE.md` (sha256 `367e450a…`).
```

**Do not flip these until the PART H soak closes on 2026-08-04.** The operator track is genuinely
done; the *change* is not closed until it has survived a trading day.

---

# FINAL REPORT — PARTS C–H

| Part | Status |
|---|---|
| STEP 0 | ✅ **Done.** Rules read-back green; the 6 missing dashboard exports captured and verified. |
| PART C | ✅ **Done.** 23 → 11 rules, **delete-in-place**. |
| PART D | ✅ **Done.** 6 → 3 dashboards; datasource pin persisted. |
| PART E | ✅ **Done.** Vars dropped; both exporter services deleted; 5 targets healthy. |
| PART F | ✅ **Done.** Both drill legs fired; every rule restored and verified. |
| PART G | ✅ **Done.** Reachable via files on disk; B.6 captured; AC-WP8 proven both directions. |
| PART H | ⏳ **Not complete — a wait, not a task.** Soak starts Mon 2026-08-03; closes Tue 2026-08-04. |

### The four headline numbers

```
rules            : 11   (0 paused)   titles == the required set exactly
stp-* dashboards : 3    (stp-trading-ops, stp-risk-ops, stp-system-health)
up targets       : 5    backend, beat, worker, worker-backtest, streams — all env=production
                        up == 0 -> empty
budget rate      : 0.1227   < 0.85   (measured on grafanacloud-usage; a real number, not EMPTY)
```

### PART C path

**Delete-in-place**, exactly as correction C1 directs. No import, no paused window, no re-binding of
the budget rules' datasource. No deviation.

### The drill — which path, and what it does and does not prove

- **Warning leg (a):** `CeleryQueueDepthHigh`, threshold `> 1000` → `> -1`. Input pre-checked for
  real samples (`max(celery_queue_depth) = 0`, not NoData). Reached **Firing**, `activeAt
  2026-08-02T08:18:50Z`. `severity=warning` ⇒ **operator-email only**.
- **Critical leg (b):** **a real `severity: critical` rule, not the label flip.**
  `MetricsBudgetExhausted`, threshold `> 1` → `> 0.01`, input ratio 0.1206 (real data). Reached
  **Firing**, `activeAt 2026-08-02T08:31:10Z`. `severity=critical` ⇒ **operator-telegram +
  operator-email** (`continue: true`). No label was mutated, so the prompt's stated risk of leaving
  a rule mislabelled `critical` never arose.
- **⚠️ Delivery is SENT, not CONFIRMED.** Grafana shows both alerts reached `Alerting`, which proves
  evaluation and routing. It does **not** prove receipt. A CLI session has no Telegram access and no
  mailbox access. **Both channels remain UNVERIFIED pending Yuval's confirmation.**

### Every rule touched — restored expression read back from the provisioning API

| rule | read back | vs committed YAML @ `5fafff0` |
|---|---|---|
| `CeleryQueueDepthHigh` | `max(celery_queue_depth) > 1000`, `warning`, `for 5m`, `isPaused false` | ✅ matches `alert-rules.yaml` |
| `MetricsBudgetExhausted` | `sum(...)*60 / scalar(...) > 1`, `critical`, `for 15m`, `isPaused false` | ✅ matches `usage-alerts.yaml` |
| `MetricsBudgetHigh` (AC-WP8 pause test) | `sum(...)*60 / scalar(...) > 0.85`, `warning`, `isPaused false` | ✅ matches `usage-alerts.yaml` |

Beyond the three touched, **all 11 rules were diffed in full against their pre-drill bodies**:
*ALL 11 IDENTICAL* (only the server-set `updated` field differs). All 11 expressions matched the
committed YAML verbatim. All rules `inactive`, none paused.

### Was PART G reachable from a CLI session?

**Yes — but not the way the prompt assumed, and my first answer was wrong.** Driving the desktop UI
needs macOS Screen Recording, which was not granted. But the scheduler's state is
`scheduled-tasks.json` and each task's prompt is a `SKILL.md` **file on disk** — both fully readable
and editable from the CLI. I initially reported PART G unreachable; that section is marked
**SUPERSEDED**. It was completed in full.

### Every uid deleted

**Alert rules (12)** — `83497f86-0098-5477-b1c1-e3f44b59c3af` (BacktestQueueWaitHigh),
`ed966504-080b-55ab-a25e-25db62a736c7` (BacktestFailureRate),
`76cb177c-58bd-5b78-8bba-8095ad2e331d` (BacktestArtifactBloat),
`acddf437-5e38-5518-9a72-680268303837` (DBConnectionSaturation),
`15517539-3cf0-5bdd-b41b-5d6d87844367` (SentimentLag),
`71062085-b3b8-5e16-84e9-c7e9308552cc` (HMMModelStale),
`bfry5i6igdh4wc` (ApiErrorBudgetFastBurn), `bfry5i6rvzo5ca` (ApiErrorBudgetSlowBurn),
`691f836a-12a0-53e4-8c09-f317a57a6ae8` (OrderSubmitLatencyHigh),
`auth-login-success`, `auth-family-revocations`, `auth-rate-limit-spike`.

**Contact point (1)** — `bfkrwig5cgohsb` (`auth-health-email`).
**Folder (1)** — `cfkrwjgh3sxkwa` (`StratTraderPro Auth`).
**Dashboards (3)** — `stp-data-pipelines`, `stp-backtest-ops`, `stp-auth-health`.
**Railway services (2)** — `postgres-exporter-prod` (`908c3207-63f1-4d59-8f8f-191d95e424a3`),
`redis-exporter-prod` (`8af7c337-867c-47f8-8fd5-8bb9ac83d89a`).
**Railway env vars (2)** — `POSTGRES_EXPORTER_TARGET`, `REDIS_EXPORTER_TARGET` on `grafana-agent`.

### Rule-compliance statement

- **No object was deleted whose backup had not been read back first.** STEP 0's gate was closed —
  including re-exporting all 6 dashboards, which had never been captured — **before** any delete.
  Each of the 3 deleted dashboards was re-verified present, parsing and non-empty in the moment
  before its `DELETE`. **RULE 9's loud-confession clause does not apply.**
- `X-Disable-Provenance: true` on **every** write (`POST`/`PUT`/`DELETE`). No object was left
  `provenance: api`.
- **Not touched in either direction:** `scrape_interval: 60s`; `MetricsPipelineDown` / `TargetDown`
  (never edited, never paused — both `inactive`/`ok` at close); `contact-points.yaml` /
  `notification-policy.yaml`; the `operator-email` / `operator-telegram` receivers;
  `BACKEND_TARGET` / `METRICS_BASIC_AUTH_*` / the four task-target env vars (all verified intact
  after the var deletes). Never alerted on `grafanacloud_org_metrics_billable_series`.
- No metrics were deleted to move a budget number. `ENABLE_LIVE_TRADING` untouched.
- **No repo commit, PR, branch switch or merge.** Repo reads were done via `git show origin/main:…`
  rather than checking out `main`, leaving the working tree untouched.
- **Secrets: one incident, disclosed above** (`REDIS_ADDR` printed by a name-based redaction filter;
  re-redacted by value shape, directory re-scanned clean, rotation left to the owner). The Grafana
  token and the Telegram bot token were never printed, exported or written anywhere.

### Things I STOPped on, or refused to do

1. **Stopped at the very start** — `GRAFANA_TOKEN` unset. Did not attempt to obtain a token. Did all
   token-independent work first (STEP 0 local read-back, B.5, the PART D transform correction), then
   waited.
2. **Did not run PART D's `walk()` as written** — measured it against `origin/main` and found it
   matches **0 nodes** in all three dashboards. Running it would have silently no-op'd and recorded a
   datasource fix that never happened.
3. **Did not force a `grafana-agent` redeploy** when Railway failed to trigger one. Read
   `agent.yaml@5fafff0` and confirmed the deleted vars were unreferenced, rather than assuming.
4. **Did not grant macOS permissions** to unblock PART G, and did not restart VS Code. Found the
   file-based route instead.
5. **Did not edit `.gitignore`, `PROGRESS.md`, the runbooks, or any other repo file** beyond this
   report. All flagged for the developer.
6. **Corrected my own false pass** — the first CHECK 3/6 verbatim comparison used `head -n -1`,
   unsupported on macOS, which produced empty files that `cmp` happily called identical. Re-run with
   a portable extractor and a non-empty guard before the ✅ was believed.

### Still owed by the owner

1. **Confirm Telegram receipt** of the `MetricsBudgetExhausted` critical page, and the two emails.
   Until then the drill is *sent, not delivered*.
2. **Rotate the exposed `strattraderpro-otlp` Cloud Access Policy token** (pasted into a transcript;
   check what is pushing OTLP with it before deleting), and decide on the **Redis password**.
3. **Delete the `adr109-cutover` Grafana service account** and `rm .env.grafana` when the soak
   closes — the token has **no expiry**, so nothing revokes it automatically.
4. **PART H:** watch Mon 2026-08-03, confirm the audit is green Tue 2026-08-04, then apply the H.4
   wording — after restoring the ADR-109 section the feature branch deletes.

---

## AC-WP8 pause leg — FULL-WINDOW RE-RUN (authoritative)

Re-executed with the **full 5-minute paused window** AC-WP8 specifies, sampling CHECK 1's assertions
once per minute across the window rather than only at t+0:

```
t+0s    PAUSE   -> HTTP 200   isPaused=true
t+60s   CHECK 1 -> paused=["MetricsBudgetHigh"]  titles_ok=true  DETECTED ✅
t+120s  CHECK 1 -> paused=["MetricsBudgetHigh"]  titles_ok=true  DETECTED ✅
t+180s  CHECK 1 -> paused=["MetricsBudgetHigh"]  titles_ok=true  DETECTED ✅
t+240s  CHECK 1 -> paused=["MetricsBudgetHigh"]  titles_ok=true  DETECTED ✅
t+300s  CHECK 1 -> paused=["MetricsBudgetHigh"]  titles_ok=true  DETECTED ✅
        UNPAUSE -> HTTP 200

PART F.1 re-gate:  total 11  |  paused []
MetricsBudgetHigh: byte-identical to pre-pause body ✅
dead-man's pair:   MetricsPipelineDown=inactive/ok   TargetDown=inactive/ok
```

`titles_ok=true` throughout is the point of the sampling: the 11-title set stayed correct the whole
time, so it is specifically the **`isPaused` assertion** that catches this — a title-or-count check
alone would have sailed past it. That is exactly the BUG-009 class the gate exists to prove against.

**Safety of the re-run:** the pause/un-pause pair ran inside a single shell invocation with an
`EXIT INT TERM` trap that restores the original body, so the rule could not have been stranded
paused had the command been killed mid-window. Budget was 0.12 against a 0.85 threshold — there was
no plausible path to a missed breach in 5 minutes.

**AC-WP8 is now satisfied to the letter as well as the intent:** runs green (14/14 assertions), and
detects a paused rule across the full specified window, restored byte-for-byte.

---

## PART H — status of each sub-step, and why the remainder is not executable today

| step | status |
|---|---|
| **H.1** "The next US trading day is Monday 2026-08-03. Sunday is not a soak." | ✅ **Recorded.** Informational; no action exists to take. |
| **H.2** watch for anything unexpectedly firing — and anything that should have fired and did not | ⏳ **Armed.** Day-0 baseline captured throughout this report; the watch mechanism is the rewritten daily audit, verified armed below. |
| **H.3** on day 2, confirm the audit run is green | ⏳ **Calendar-gated — Tue 2026-08-04.** |
| **H.4** tell the human the two `⏳ PENDING` lines are ready to flip, with exact wording | ✅ **DELIVERED** — full replacement text for `origin/main:130-134` and `:135-136` is in the H.4 section above, together with the blocking discovery that the current branch deletes the whole ADR-109 section. Per the prompt, the edit itself is **not** made by this session. |

### The durable mechanism is armed and verified

```
id        : strattraderpro-silent-failure-audit
cron      : 0 9 * * *      enabled: true      model: claude-sonnet-5
filePath  : ~/Documents/Claude/Scheduled/strattraderpro-silent-failure-audit/SKILL.md
prompt    : 13086 bytes (was 9359) — rewritten 2026-08-02 14:41
            asserts the 11-title set ✅ | exactly 5 targets ✅ | budget empty=FAIL ✅
            stale "Known ongoing: Auth login success rate" exception REMOVED ✅
fires     : Mon 2026-08-03 09:00 IL  (soak day 1)
            Tue 2026-08-04 09:00 IL  (H.3 evidence)
green run emits: "OK — 6/6 checks passed."
```

This runs from the OS scheduler and the on-disk prompt — **independent of any Claude session.** It is
the same mechanism plan WP-8 designates, now carrying the post-cutover assertions.

### Why no session cron job was created to "close" H.3

`CronCreate` was considered and **deliberately rejected**. Its contract: *"Jobs live only in this
Claude session — nothing is written to disk, and the job is gone when Claude exits"*, and *"Jobs only
fire while the REPL is idle."* A job scheduled Sunday afternoon for Monday 09:00 would in all
likelihood not exist when the time came, and would fire only if the REPL happened to be idle and
open.

Creating one would have produced a **mechanism that looks like coverage and silently is not** — the
precise failure class this entire cutover exists to eliminate (BUG-009: alerting that reports
`health: ok` because it never evaluates). Manufacturing false assurance to tick a completion box
would be a worse outcome than an honestly open item. **Recorded as a deliberate refusal, not an
oversight.**

### What "PART H complete" will require, and who does it

Nothing further is executable from this session. On **Tue 2026-08-04**, read the audit's output:

- `OK — 6/6 checks passed.` ⇒ H.3 green ⇒ the change closes ⇒ apply the H.4 wording (after restoring
  the ADR-109 section the feature branch deletes).
- Any failure block ⇒ the soak found something; do **not** flip the PENDING lines; triage per the
  named bug docs.

**The operator track (C–G) is complete. The change is not closed until the soak says so — which is
the prompt's design, not an omission.**

---

# SESSION 2 — 2026-08-02, 15:40–16:10 IDT (pre-soak)

Scope: everything in `HANDOFF-ADR-109-SESSION-2.prompt.md` that is executable before the soak opens.
Read-only against production except this file. **No repo commit, no PR, no branch switch.**

## Preflight — every handoff number RE-VERIFIED against the live API

```
rules                : 11        paused: []          all health=ok, all state=inactive
titles               : AuditIntegrityFailure, BrokerStreamSilent, CeleryQueueDepthHigh,
                       KillSwitchFlattenSlow, KillSwitchTriggered, MetricsBudgetExhausted,
                       MetricsBudgetHigh, MetricsPipelineDown, TargetDown,
                       WebhookErrorRatioCrit, WebhookErrorRatioWarn        == the required set
stp-* dashboards     : 3         stp-risk-ops, stp-system-health, stp-trading-ops
up targets           : 5         backend, beat, streams, worker, worker-backtest — all env=production
up == 0              : 0 results
budget ratio         : 0.1227    < 0.85, a real number (not EMPTY)
firing               : []
folders (top-level)  : GrafanaCloud, StratTraderPro    — `StratTraderPro Auth` 404s (uid cfkrwjgh3sxkwa)
contact points       : operator-email, operator-telegram only — `auth-health-email` gone
Railway services     : 11, neither exporter present    (postgres-exporter-prod / redis-exporter-prod)
dead-man's pair      : MetricsPipelineDown inactive/ok, TargetDown inactive/ok — untouched
branch               : feat/data-provider-keys-ui, tracked files modified: 0
```

**Nothing drifted. No rule came back paused. No STOP condition met.**

## Owner action 1 — ALERT DRILL: email leg is now **CONFIRMED DELIVERED**, not merely sent

Read from the mailbox (`yuval3000@gmail.com`), sender `grafana@yuval3000.grafana.net`. All four
messages are present and still unread:

| # | subject | delivered | vs `activeAt` |
|---|---|---|---|
| `19fc18e64e36e271` | `[FIRING:1] CeleryQueueDepthHigh … (warning)` | 2026-08-02T08:19:22Z | activeAt 08:18:50Z → **+32s** |
| `19fc192fa02e37c5` | `[RESOLVED] CeleryQueueDepthHigh … (warning)` | 2026-08-02T08:24:22Z | — |
| `19fc199ae671f105` | `[FIRING:1] MetricsBudgetExhausted … (critical)` | 2026-08-02T08:31:41Z | activeAt 08:31:10Z → **+31s** |
| `19fc247a37b2da96` | `[RESOLVED] MetricsBudgetExhausted … (critical)` | 2026-08-02T11:41:41Z | — |

⇒ **`operator-email` is proven end-to-end for both a `warning` and a `critical`.** The critical leg's
delivery also proves the policy tree's `continue: true` fan-out reached email.

⚠️ **Telegram remains UNVERIFIED.** `operator-telegram` is the *only* receiver still unproven, and
only the owner can check that chat. The critical page routes to both, so the email arriving does
**not** prove the Telegram leg. Still owed.

## NEW FINDING — the critical drill rule held its lowered threshold for **3h06m**

Pulled from `/api/v1/rules/history` (state history, not inferred):

```
MetricsBudgetExhausted   uid afrt3kqzdnawwc
  08:15:50Z  Normal (NoData) -> Normal (Updated)     <- threshold lowered  > 1  ->  > 0.01
  08:16:10Z  Normal          -> Pending
  08:31:10Z  Pending         -> Alerting             <- pages Telegram + email
  11:37:10Z  Alerting        -> Normal (Updated)     <- threshold RESTORED  > 0.01 -> > 1

CeleryQueueDepthHigh     (for contrast — clean)
  08:13:50Z  Normal   -> Pending  (threshold lowered)
  08:18:50Z  Pending  -> Alerting
  08:21:00Z  Alerting -> Normal (Updated)            <- restored after 2m10s
```

The warning leg was restored in **2m10s**. The critical leg was left holding `> 0.01` and sitting in
`Alerting` for **3 hours 6 minutes**. §F.4's tick-off is accurate as an *end state* — the expression
does read back `> 1` and did so at close — but the report's ordering implies a prompt restore, and it
was not. Recording the actual timeline.

**Blast radius, measured not assumed:** exactly one `[FIRING:1]` email and one `[RESOLVED]` email
were sent for this rule — no repeat pages, because the window (3h06m) stayed under the notification
policy's repeat interval. **Nothing else was affected**, and the drill rule is a non-money-path
budget rule. Impact is a lesson, not damage.

**Lesson for the next drill:** restore inside the same shell invocation with an `EXIT INT TERM` trap,
exactly the way the AC-WP8 pause leg was later run. The pause leg got this right; the F.3(b) leg
did not.

## Owner action 2 — the OTLP token IS IN ACTIVE USE. **Do not delete it before minting a replacement.**

The handoff says "check what is pushing OTLP with it *before* deleting". Checked:

```
Railway services carrying OTEL_EXPORTER_OTLP_ENDPOINT + OTEL_EXPORTER_OTLP_HEADERS   (names only,
no values read or printed):
    backend, celery-worker, celery-beat, streams-prod, worker-backtest-prod, ws        = 6 services
Services without them: frontend, grafana-agent, ib-gateway
```

Traces are arriving **right now** — Tempo (`grafanacloud-traces`), last 24h:

```
service.name values : ["strattraderpro-backend"]     (sole reporter)
most recent spans   : 2026-08-02 12:30:47Z  BZPOPMIN
                      2026-08-02 12:30:37Z  run/apps.orders.tasks.fill_ingestor
                      2026-08-02 12:30:31Z  EVAL
```

⇒ Deleting `strattraderpro-otlp` outright would **silently kill tracing on six production services**.
Required order: (1) mint a replacement token on the same Cloud Access Policy, (2) update
`OTEL_EXPORTER_OTLP_HEADERS` on all six services, (3) confirm traces still land in Tempo, (4) *then*
delete the exposed token. Owner action — a CLI stack token (`glsa_`) cannot manage grafana.com Cloud
Access Policies, and this touches six production services.

## H.2 pre-soak — today's scheduled audit run raised a "live silent failure". **Investigated and CLOSED as benign.**

The `strattraderpro-silent-failure-audit` task fired on schedule today at **2026-08-02T06:09:21Z**
(09:09 IL). That run used the **pre-rewrite** prompt (the rewrite landed 14:41), so its stale
baselines (23 rules / 7 targets) were always going to complain. Its `CHECK 2 FAILED` on the two
absent exporters is the cutover working as designed and needs no action.

Its *connected finding* did need checking, because it is precisely the class H.2 says to watch for:

> `auth_login_total{service="backend"}` has returned zero series since **2026-08-01T18:43:03Z**, while
> `backend`'s own `up` stayed healthy — "looks healthy, isn't", currently live.

**Root cause found; it is benign.**

1. `backend/apps/users/metrics.py:19` — `auth_login_total` is a **labelled** Counter
   (`labelnames=("result",)`). `prometheus_client` emits **no series at all** for a labelled Counter
   until `.labels(...)` is first called, and the multiprocess metric files are wiped on process start.
2. Railway deploy history, `backend`: a deployment at **2026-08-01T18:42:19Z**
   (`chore(observability): reduce Grafana to the safety…`). The metric's last datapoint is
   **18:43:03Z** — the same redeploy.
3. ⇒ The counter is absent because the backend restarted and **nobody has logged in since**. Not a
   pipeline failure.

Cross-checked that the pipeline itself is healthy, per job:

```
count({job="backend"})          = 559 series      django_http_responses_…_total = 1 series (36)
count({job="worker"})           = 202             celery_queue_depth            = 2 series
count({job="beat"})             = 157
count({job="streams"})          = 152
count({job="worker-backtest"})  = 157
```

**This retroactively validates deleting the auth rules.** `auth-login-success` computed a ratio whose
denominator was `clamp_min`'d — so with the numerator series *entirely absent*, it read as 100%
failure on an idle instance. The metric's absence is normal for a freshly-deployed idle backend; the
rule turned normal into a page. Exactly the defect ADR-109 removed.

⚠️ **Follow-through for the owner:** `bad_password`/`ok` series will reappear on the first real login.
Nothing to fix. But if you ever want a *positive* liveness signal on auth, it must be built on a
metric that exists at zero traffic — not on a labelled counter that vanishes with the process.

## Where Tuesday's H.3 evidence will actually be readable

The scheduled task writes no summary file; its output is the final assistant message of a
per-run session transcript on disk. Resolved and verified against today's run:

```
1. registry     ~/Library/Application Support/Claude/local-agent-mode-sessions/
                  6b708088-141f-40a1-ae49-68ebbd14ed2b/504f3a1c-a3bf-4e49-9a25-0b6cd29f3569/
                  scheduled-tasks.json
                -> the run's session id + createdAt
2. that dir     local_<sessionId>.json          # createdAt == the run; title "Strattraderpro …"
3. transcript   local_<sessionId>/.claude/projects/<encoded-outputs-path>/<cliSessionId>.jsonl
                -> last {"type":"assistant"} text block == the audit verdict
```

Today's run resolved to `local_f547433b-7350-4985-b745-616874f716fd` /
`7a1f987a-201c-4ab3-a869-8fd264b00a1f.jsonl`, verdict timestamped 2026-08-02T06:17:18Z. The same
walk will find Monday's and Tuesday's.

## The soak mechanism — re-verified armed, unchanged since session 1

```
id        : strattraderpro-silent-failure-audit    enabled: true    cron: 0 9 * * *
model     : claude-sonnet-5                        permissionMode: bypassPermissions
filePath  : ~/Documents/Claude/Scheduled/strattraderpro-silent-failure-audit/SKILL.md
size      : 13086 bytes   mtime 2026-08-02 14:41
sha256    : 4e8030800d56bb6d95edc4aad833b1316cfbd98ea24ea0527f6a36fbe2fa8e58
lastRunAt : 2026-08-02T06:09:21Z   (PRE-rewrite prompt — see above)
next runs : Mon 2026-08-03 09:00 IL  = soak day 1, FIRST run of the rewritten prompt
            Tue 2026-08-04 09:00 IL  = H.3 evidence
green     : "OK — 6/6 checks passed."
```

## PART H status — unchanged, and it is a calendar gate, not a task

| step | status |
|---|---|
| H.1 | ✅ Recorded. Sunday 2026-08-02 is not a soak day. |
| H.2 | ⏳ **Armed.** Day-0 baseline re-captured above; the one live finding raised so far is closed as benign. |
| H.3 | ⏳ **Gated on Tue 2026-08-04.** Not executable earlier by any means. |
| H.4 | ✅ Wording delivered; **do not flip** until H.3 is green, and restore the ADR-109 section the branch deletes. |

**Nothing further in the handoff is executable before Mon 2026-08-03 09:00 IL.**

## Still owed by the owner — updated

1. ~~Confirm the two drill **emails**~~ → **CONFIRMED by this session** (message ids above).
   **Telegram receipt for the `MetricsBudgetExhausted` critical page is still the one open leg.**
2. **Rotate `strattraderpro-otlp`** — now with evidence: **in active use by 6 services**, traces
   landing as of 12:30Z today. **Mint-then-swap-then-delete**, never delete-first.
3. **Decide on the Redis password.** Unchanged — owner's call.
4. **Teardown when the soak closes:** delete the `adr109-cutover` service account (the only thing
   that revokes the non-expiring token), then `rm .env.grafana`.
5. **H.3 Tue 2026-08-04**, then H.4 — after restoring the ADR-109 `PROGRESS.md` section.

## Rule-compliance statement (session 2)

- **Read-only against production.** No `POST`/`PUT`/`DELETE` of any kind was issued to Grafana or
  Railway this session, so the `X-Disable-Provenance` rule had nothing to apply to.
- **Not touched in either direction:** every never-touch item was *read* and confirmed intact —
  the `MetricsPipelineDown`/`TargetDown` pair, both contact points, all 11 rules, the five task
  targets. Nothing was written.
- **No secrets printed.** Railway variables were enumerated by **name only**; no value of
  `OTEL_EXPORTER_OTLP_HEADERS`, `METRICS_BASIC_AUTH_*`, `REDIS_ADDR` or the Grafana token was read
  into output. `ENABLE_LIVE_TRADING` untouched.
- **No repo commit, PR, branch switch or merge.** The only file written is this report.
- **The RULE 10 findings list was left alone** — not fixed, not partially fixed. Still the
  developer's call.
- **No new scheduled job was created.** Session 1's reasoning against manufacturing a second,
  weaker mechanism still holds; the on-disk task already covers Mon and Tue.

---

# SESSION 2, PART B — pre-soak verification of the three things taken on trust

Session 2's first pass accepted three of the handoff's claims without checking them. All three are
now checked. **One of them is wrong**, and it is the one carrying a ⛔.

## B1. Rollback set — **VERIFIED INTACT.** The soak has a real safety net.

Every artifact in the handoff's rollback table, re-read and parsed today:

| artifact | verified |
|---|---|
| `adr109-rules-backup.json` | parses, **23 rules**, none paused |
| `deleted-rule-bodies.jsonl` | **12 lines**, all 12 titles ⊆ the 23-rule backup |
| ↳ restorability | all 12 carry `title`+`condition`+`data`+`folderUID`+`ruleGroup`+`orgID` ⇒ **POST-restorable** |
| `adr109-dashboard-stp-*.json` (6) | all parse; panels 4 / 16 / 11 / 11 / 25 / 14, uid+title intact |
| `deleted-contact-point-auth-health-email.json` | `bfkrwig5cgohsb` / `auth-health-email` / email |
| `deleted-grafana-agent-vars.json` | `postgres-exporter-prod…:9187`, `redis-exporter-prod…:9121` — **the `-prod` suffix warning is correct**; the B.5 runbook's unsuffixed names would not resolve |
| `daily-audit-prompt-BEFORE.md` | sha256 `367e450a1992e38c…` — **MATCHES** the handoff |
| `railway-exporter-services-manifest.json` | both services, image+digest+region+replicas |

Rollback is genuinely available. Recreate rules with `POST` (not `PUT`) and re-check `isPaused`.

## B2. ⛔ **CORRECTION — the H.4 "blocking discovery" is WRONG. Do not restore anything.**

The handoff and §H.4 both state: *"the branch deletes the entire ADR-109 section from `PROGRESS.md`
… Merging that branch as-is silently erases the ADR-109 record. Restore that section on merge."*

**Following that instruction would duplicate the section.** Simulated the actual merge in memory
(`git merge-tree --write-tree origin/main HEAD` — no working-tree or index change):

```
merge-base                : 6b7059c        branch is missing BOTH ADR-109 commits:
                                             5fafff0  reduce Grafana to the safety core (#50)
                                             aa16811  ADR-109 operator cutover prompt (#51)
merged project-plan/PROGRESS.md : 169 lines
  ## The 2026-08-01 observability rightsizing (ADR-109)   -> PRESENT, merged line 122
  - **Operator track: ⏳ PENDING `[LIVE]`**               -> PRESENT, merged line 131
  - **Daily audit: ⏳ PENDING**                            -> PRESENT, merged line 136
  git reports: "Auto-merging project-plan/PROGRESS.md"   -> NO CONFLICT
ADR-109-deleted files in the merge result:
  docs/slo.md ............................ correctly absent
  infra/grafana/auth-health-dashboard.json correctly absent
  infra/grafana/backtest-ops-dashboard.json correctly absent
  infra/grafana/data-pipelines-dashboard.json correctly absent
CI-enforced configs in the merge result:
  infra/grafana/alerts/alert-rules.yaml  027dcfe…  IDENTICAL to main
  infra/grafana-agent/agent.yaml         199904b…  IDENTICAL to main
ONLY conflict in the whole merge: CHANGELOG.md (content) — both sides appended entries. Routine.
```

**Why session 1 got it wrong:** it compared the *working tree* against `origin/main` and saw the
section missing. That is expected and harmless — the branch was cut at `6b7059c`, which predates
#50, so the section never existed on the branch to be deleted. Git's 3-way merge sees *added on
main, untouched on branch* and keeps it. A two-way `diff` cannot distinguish "deleted by this
branch" from "added on the other side after the fork"; only the merge base can, and it was not
consulted.

**Revised H.4 instruction:** merge normally, resolve the CHANGELOG conflict by keeping both sides,
then apply the §H.4 replacement wording to the two `⏳ PENDING` bullets at **merged lines 131 and
136**. **No restoration step. The ⛔ is withdrawn.** (Also: the section is **17** lines, `origin/main`
121–137, not 18.)

## B3. The seven RULE-10 findings — re-verified. **Five stand exactly, two need amending.**

Still not fixed — still the developer's call. Verified only so the list is trustworthy.

| # | finding | verdict |
|---|---|---|
| 1 | `system-health-dashboard.json` panel description → "the Auth Health board's `bad_password` counter" | ✅ **stands** — line **515** (handoff said "panel 8") |
| 2 | four runbooks point at the deleted Auth Health dashboard | ✅ **stands, all four line numbers exact** — `user-locked-out.md:45`, `password-reset-abuse.md:56`, `user-lost-mfa.md:93`, `prod-bootstrap.md:152` |
| 3 | `bugs/README.md:31` says BUG-009 "FIXED (all 21 live)"; live count is 11 | ✅ **stands**, line 31 exact |
| 4 | `setup-guides/grafana-setup.md:67` gives `strattraderpro.grafana.net`, "does not resolve" | ⚠️ **wrong on all three counts** — see below |
| 5 | AC-R5 wording should say `StratTraderPro/stp-alert-rules.prom.yaml` | ⚠️ **no tracked file contains `AC-R5`** — see below |
| 6 | `stp-adr109-backup-2026-08-01/` is not gitignored | ✅ **stands** (`git check-ignore` → not ignored; still untracked) |
| 7 | grep `clamp_min` in any other ratio denominator | ✅ **executed — answered below** |

**On #4:** it is at line **60**, not 67; `strattraderpro.grafana.net` **does resolve**
(→ `104.18.13.97`; `*.grafana.net` is a Cloudflare wildcard, so *every* stack name resolves); and the
line is a **worked example inside the signup walkthrough** — *"Choose a stack name, e.g.
`strattraderpro`. Your stack URL becomes …"* — not a broken pointer to this project's stack. Line 31
of the same file already uses the `YOUR_ORG` placeholder. At most a consistency nit; **the finding as
written should be struck**, not actioned.

**On #5:** `git grep AC-R5` returns **nothing tracked**. Every hit is in the three untracked
`*.prompt.md` files at the repo root. There is no committed acceptance-criteria document to amend, so
this is an edit to the prompt, not to the repo — it will vanish with the prompts unless the wording is
carried into whatever doc supersedes them.

## B4. Finding #7 answered in full — **the defect is gone from alerting, and the survivors are fail-safe**

```
LIVE alert rules using clamp_min : 0 of 11
```

The two live ratio rules (`WebhookErrorRatioWarn`/`Crit`) divide without a clamp, so an idle instance
yields an **empty** result — NoData, not a false page. That is the safe construction.

`clamp_min` still appears in **four committed dashboard panels** (plus the backup copies). None is an
alert rule, so none can page — and every one is **oriented safely**:

| file:line | numerator | idle behaviour |
|---|---|---|
| `trading-ops-dashboard.json:613` | `webhook_received_total{result!="accepted"}` — failures | → 0 = healthy ✅ |
| `backtest-ops-dashboard.json:374` | `backtest_failed_total` — failures | → 0 = healthy ✅ |
| `system-health-dashboard.json:370` | `status=~"5.."` (+ `or vector(0)`) | → 0 = healthy ✅ |
| `system-health-dashboard.json:1211` | `status=~"5.."` (+ `or vector(0)`) | → 0 = healthy ✅ |

**The orientation is what makes it dangerous, not the `clamp_min`.**

- `failures / clamp_min(total, ε)` with a `>` threshold → idle reads **0 = healthy**. Fail-safe.
- `successes / clamp_min(total, ε)` with a `<` threshold → idle reads **0 = total failure**. Fail-loud.

The fail-loud orientation existed in exactly two places, both auth: the deleted `auth-login-success`
rule, and `infra/grafana/auth-health-dashboard.json:114,485` (`result="ok"` numerator). **That file is
already deleted on `origin/main` by #50** and is only present in the working tree because the branch
predates it — the merge drops it (verified in B2). ⇒ **No action required. The grep is closed.**

## B5. Bonus finding — the branch carries three other ADR-109-deleted files, and the merge handles them

`docs/slo.md`, `auth-health-dashboard.json`, `backtest-ops-dashboard.json`,
`data-pipelines-dashboard.json` are all still in the working tree for the same reason as the
PROGRESS.md section: the branch predates #50. **All four are correctly absent from the merge result**
(B2). No action — but do not "helpfully" re-add them when resolving the CHANGELOG conflict.

## Rule-compliance statement (session 2, part B)

- **Still entirely read-only.** `git merge-tree --write-tree` writes only to the object store; the
  working tree, the index and `HEAD` were never touched. `git status` is unchanged: 6 untracked
  entries, **0 tracked files modified**. No commit, no branch switch, no merge performed.
- **No production writes.** Nothing was sent to Grafana or Railway in this pass.
- **The RULE 10 list was verified, not fixed.** Two entries are marked for amendment; neither file
  was edited.
- **The empty-extraction trap was hit and caught:** the first `PROGRESS.md` check ran against the
  repo root, where the file does not exist (it is `project-plan/PROGRESS.md`). The guard printed the
  path error instead of a silent "NOT FOUND", and every later extraction was `test -s`-gated before
  any comparison was believed — per the handoff's gotcha 2.

---

# SESSION 2, PART C — Telegram CONFIRMED, and a day-0 "can every rule actually fire?" audit

## C1. ✅ **THE DRILL IS NOW FULLY CONFIRMED ON BOTH CHANNELS.** Owner action 1 is CLOSED.

Yuval supplied the `strat_trader_pro_bot` Telegram messages. Both legs received:

```
Firing    alertname = MetricsBudgetExhausted   severity = critical
          Value: prometheus_math=1, query=0.1207, threshold=1
          Source: …/alerting/grafana/afrt3kqzdnawwc/view
Resolved  alertname = MetricsBudgetExhausted   severity = critical
          grafana_state_reason = Updated
```

| channel | warning leg | critical leg |
|---|---|---|
| `operator-email` | ✅ confirmed (2 msgs) | ✅ confirmed (2 msgs) |
| `operator-telegram` | n/a — policy routes warning to email only | ✅ **confirmed (2 msgs)** |

⇒ **PART F's "SENT, not CONFIRMED" caveat is lifted.** The policy tree is proven end-to-end: a
`severity: critical` reaches Telegram *and*, via `continue: true`, email; a `severity: warning`
reaches email only. That is exactly the designed routing.

**Two independent corroborations fall out of the Telegram payload:**

1. `query=0.1207` matches the value in the state-history transition at `08:31:10Z` to the digit —
   the same evaluation, seen from a third channel.
2. `grafana_state_reason = Updated` on the Resolved message **independently confirms Session 2's
   3h06m finding**: the alert cleared because the *rule was edited* (threshold restored), **not**
   because the condition stopped being true. Grafana, the state history and Telegram all agree.

## C2. Day-0 wiring audit — **can each of the 11 rules actually fire?**

H.2's harder half is *"anything that should have fired and did not."* The worst version of that is a
rule wired to a metric name **nothing emits** — indistinguishable from a quiet, healthy rule, and
permanently unable to fire. Session 1 observed that 6 criticals have no input series and called it
"expected on an idle instance", but never separated *latent* from *broken*. Done now.

**Every metric name resolves. Zero typos. No rule is incapable of firing.**

| metric | 30d series | verdict |
|---|---|---|
| `audit_integrity_check_total` | 1 | ✅ live |
| `broker_stream_heartbeat_age_seconds` | 1 | ✅ live |
| `celery_queue_depth` | 2 | ✅ live |
| `killswitch_flatten_latency_seconds_bucket` | 50 | ✅ live |
| `django_http_responses_total_by_status_total` | 7 | ✅ live |
| `grafanacloud_instance_samples_per_second` / `_included_series` | — | ✅ live (ratio 0.1227) |
| `up{service="backend"}` | 1 | ✅ live — see C3 |
| **`killswitch_trigger_total`** | **0 — never seen in 30d** | ✅ **latent by design, not broken** |

**Why `killswitch_trigger_total` is absent, and why that is fine:**

```python
# backend/apps/risk/metrics.py
KILLSWITCH_TRIGGER = Counter("killswitch_trigger_total", …, labelnames=("scope",))   # LABELLED
KILLSWITCH_FLATTEN_LATENCY = Histogram("killswitch_flatten_latency_seconds", …)      # UNLABELLED
```

The name in the rule matches the code **exactly**. A **labelled** `prometheus_client` Counter exports
**no series at all** until the first `.labels(...)` call; an **unlabelled** one registers at import
and exports 0 immediately. That single distinction explains the whole "6 criticals have no input
series" observation — and it is the *same* mechanism behind the `auth_login_total` scare closed in
Session 2 Part A. It is a property of the client library, not a fault.

⚠️ **One real caveat to carry into the soak:** a latent rule cannot fire on the *instant* its metric
first appears. `increase()`/`rate()` need ≥2 samples in the window, so at a 60s scrape expect
**~1–2 minutes of extra latency on the very first event** for `KillSwitchTriggered`,
`WebhookErrorRatio{Warn,Crit}` and `AuditIntegrityFailure`. They fire — just not on the first scrape.
Not a defect; worth knowing before someone reads the delay as a miss.

## C3. The dead-man's pair — selector verified against the real label set

`MetricsPipelineDown` is `absent(up{service="backend"})`. If the `service` label did not exist, the
selector would match nothing, `absent()` would return 1, and the rule would page forever. Checked:

```
up{service="backend"}         -> 1 series, value 1
absent(up{service="backend"}) -> EMPTY            (= healthy, correct)
actual label set on up        -> {__name__, cluster=strattraderpro-production, env=production,
                                  instance=backend.railway.internal:8000, job=backend, service=backend}
```

✅ Correctly wired. The `service` label is present and populated.

## C4. `noDataState` / `execErrState` — checked, and it is deliberate documented design

Live: **10 of 11 rules carry `execErrState: OK`**; only `MetricsPipelineDown` has
`execErrState: Alerting`. That looks alarming — a query *error* reading as healthy is the BUG-008
shape. It is not drift. `infra/grafana/alerts/alert-rules.yaml` (origin/main) specifies exactly this
and explains why, at length:

```
#   MetricsPipelineDown : noDataState=OK, execErrState=Alerting
#   TargetDown          : noDataState=OK, execErrState=OK
#
# It is tempting to give the dead-man's switch noDataState=Alerting … That is
# backwards, and it was tried: `absent(X)` returns an EMPTY vector exactly when X
# is PRESENT, i.e. when the pipeline is HEALTHY … the datasource-unreachable case
# … surfaces as an *Error*, not NoData, so it is covered by execErrState=Alerting.
```

**Live matches committed intent on both rules, exactly.** The compensating control is real: every
self-filtering rule may fail quiet, and `MetricsPipelineDown` is the single rule that fails **loud**
on evaluation error. That is the designed dead-man's switch. ⛔ Do not "fix" `execErrState` on the
other ten — the comment block records that this was already tried and caught.

## C5. The wiring class is already CI-guarded — my audit only confirms the guard works

`backend/config/test_alert_rules.py` (committed, referenced from the YAML header) parses every
`expr` in `infra/grafana/alerts/*.yaml`, extracts referenced series, and asserts each resolves to a
metric exported by some `backend/apps/*/metrics.py` or to an explicit `_EXTERNAL` allowlist
(`up`, the two `django_http_*` series, the `grafanacloud_*` usage series). **A renamed or removed
metric fails CI.**

⇒ The "rule points at a metric nothing emits" failure class is structurally prevented, not merely
absent today. My manual sweep found zero mismatches, which is the expected result if the guard is
working — and is independent evidence that it is.

## Day-0 conclusion for H.2

```
11/11 rules wired to metrics that exist or provably will exist on first event
 0/11 rules incapable of firing
 0/11 rules would page on NoData
 1/11 rules pages on evaluation error — the dead-man's switch, by design
 0    live rules use clamp_min (Part B4)
 0    drift between live noDataState/execErrState and committed intent
```

**The reduced set is not merely quiet — it is quiet for verified reasons.** That is the strongest
day-0 baseline available before the market opens, and it is the specific thing H.2 asks to be able to
distinguish on Monday.

## Rule-compliance statement (session 2, part C)

- **Read-only throughout.** Queries and `git show` only; no writes to Grafana, Railway or any tracked
  repo file. The dead-man's pair was **read**, never modified.
- **A near-miss caught:** the first 30-day metric sweep passed all seven names as a single unquoted
  `$METRICS` string — **zsh does not word-split unquoted variables**, so it queried one nonsense
  metric and printed `NEVER SEEN IN 30d`, which would have been read as *every* rule being broken.
  Re-run with an explicit list. Same family as the handoff's gotcha 2: a malformed query and a true
  negative look identical unless you check the shape of what you sent.
- **No conclusion drawn from absence alone.** Every "no series" result was chased into the source
  before being labelled benign.

---

# OPEN ITEMS — authoritative, supersedes every earlier "still owed" list

As of **2026-08-02 ~16:40 IDT**. Earlier lists in this report are superseded where they conflict.

| # | item | status |
|---|---|---|
| 1 | Alert drill delivery — email **and** Telegram | ✅ **CLOSED** (Session 2 Parts A + C) |
| 2 | Rotate `strattraderpro-otlp` CAP token | 🔶 **OWNER.** Evidence gathered: **in active use** by 6 Railway services, traces landing 12:30Z today. **Mint → swap all 6 → verify → delete.** Never delete-first. |
| 3 | Redis password decision | 🔶 **OWNER.** Unchanged; exposure limited to a private-network URI. |
| 4 | PART H.2 — soak day 1 | ⏳ **Mon 2026-08-03.** Day-0 baseline is as strong as it can be made (Part C). Audit fires 09:00 IL. |
| 5 | PART H.3 — confirm audit green | ⏳ **Tue 2026-08-04 09:00 IL.** Green = `OK — 6/6 checks passed.` Read it via the transcript walk in Session 2 Part A. |
| 6 | PART H.4 — flip the two PENDING lines | ⏳ **After H.3.** ⚠️ **Use the REVISED instruction in Part B2** — merge normally, resolve the `CHANGELOG.md` conflict, then edit merged lines **131** and **136**. **No restoration step; the earlier ⛔ is withdrawn.** |
| 7 | Teardown — delete the `adr109-cutover` service account, then `rm .env.grafana` | ⏳ **When the soak closes.** The token has **no expiry**; nothing else revokes it. |
| 8 | RULE-10 repo findings | 🔶 **DEVELOPER.** 5 stand, **#4 should be struck** (wrong on line number, resolution and intent), **#5 is untracked-only**. #7 is **closed** — no action needed. |

**Nothing on this list is executable by a CLI session before Mon 2026-08-03 09:00 IL.** Items 2, 3
and 8 are owner/developer decisions; 4–7 are calendar gates.

---

# SESSION 2, PART D — RULE-10 fixes applied + a durable H.3 check armed

Both actions were **explicitly authorised by Yuval** mid-session. Everything before this point in
Session 2 was read-only; this section is the first to modify tracked repo files.

## D1. The five standing RULE-10 findings — **APPLIED** (working tree only, no commit)

| file | change |
|---|---|
| `docs/runbooks/user-locked-out.md:45` | → Grafana **Explore**, `sum by (result) (rate(auth_login_total{result="locked"}[5m]))` |
| `docs/runbooks/password-reset-abuse.md:56` | → Explore, `rate(auth_password_reset_total{step="requested"}[5m])` |
| `docs/runbooks/user-lost-mfa.md:92-95` | states plainly there is **no** MFA-reset metric; count by hand or add a counter |
| `docs/runbooks/prod-bootstrap.md:152-155` | Auth Health → **System Health** (`stp-system-health`), which survives and has the `env` variable |
| `bugs/README.md:31` | "FIXED (all 21 live)" → "FIXED (21 live at the time of the fix; 11 after the ADR-109 rightsizing, 0 paused)" |
| `.gitignore` | + `stp-adr109-backup-2026-08-01/` — the backup dir no longer shows in `git status` |
| `infra/grafana/system-health-dashboard.json` | 3 edits — see D2 |

### ⚠️ Three of the four runbook pointers were **already wrong before ADR-109**

The deleted board's real panels were: *Login success rate*, *Login outcomes by result*,
*Refresh family revocations*, *Rate-limit hits (429) by view*. There was **never** a lockout panel,
a password-reset panel, or an MFA-tickets panel. So the runbooks were not made stale by the
cutover — they pointed at panels that never existed, and the cutover merely made that visible.

They were therefore **not** repointed at another dashboard; each now names the **metric** an operator
can actually query. For MFA the honest answer is recorded: the codebase exports **no** MFA metric at
all, so the guidance says so rather than inventing a destination.

## D2. `system-health-dashboard.json` — finding #1 understated it; **three** dangling refs, not one

The sweep after applying #1 found two more references to the deleted board **in the same file**:

1. `:515` (the flagged one) — panel description → now cites `auth_login_total{result="bad_password"}`.
2. `:18` — the board's own description ended *"Sibling dashboard: Auth Health (/d/stp-auth-health)"* → removed.
3. `:22-34` — **a live dashboard `links` entry titled "Sibling: Auth Health" pointing at
   `/d/stp-auth-health`.** This is a navigation button rendered on the **live** System Health board
   that **404s today**. Removed. More user-visible than the flagged description, and finding #1
   missed it entirely.

Verified after editing: JSON parses, 25 panels intact, `links` now holds only the plan link, and
**no `stp-auth-health` reference remains anywhere in the file**.

### Merge safety — checked, not assumed

Of the 7 edited files, 6 were **byte-identical to `origin/main`**, so those edits cannot conflict.
Only `system-health-dashboard.json` differs from main (#50 touched it). The three target regions were
confirmed **identical across merge-base `6b7059c`, `origin/main`, and the working tree** — i.e. #50
did not touch them — so a branch-side edit merges cleanly.

**CI risk: none.** `backend/config/test_alert_rules.py` scans `infra/grafana/alerts/*.yaml`, which was
not touched. No workflow in `.github/workflows/` validates `infra/grafana/*.json`, docs or runbooks.

**Not committed.** `git status` shows 7 modified tracked files, staged by nobody. The developer reviews.

## D3. Durable H.3 check — **ARMED** as a local desktop task

### Why not a cloud routine

A scheduled **cloud** agent cannot do this job: the H.3 evidence is a transcript under
`~/Library/Application Support/Claude/…` on this Mac, and the Grafana token lives in `.env.grafana`,
which is gitignored and therefore absent from any cloud checkout. A cloud agent would have neither.
**A local desktop task is the only mechanism that can actually perform the check** — and it is the
same mechanism the daily audit already uses.

This also answers Session 1's objection differently than `CronCreate` did. Session 1 correctly
rejected `CronCreate` because those jobs are session-scoped and die when Claude exits. A desktop
task is on-disk state read by the OS scheduler — it survives session exit, which was the whole
objection.

```
id         : adr109-h3-soak-verdict
cron       : 0 10 4 8 *          -> 10:00 IL, Tue 2026-08-04 (one-shot in practice)
enabled    : true                 model: claude-sonnet-5   permissionMode: bypassPermissions
filePath   : ~/Documents/Claude/Scheduled/adr109-h3-soak-verdict/SKILL.md
size       : 7084 bytes
sha256     : 0442f988337d2603f38787bb0eac291ed99505100bf60b6a1033bb33ce8b732d
folder     : ~/Documents/Claude/Projects/StratTraderPro
timing     : the audit fires 09:00 and took ~8 min on 2026-08-02 -> ~40 min margin
```

**What it does:** walks the transcript path to read Tuesday's audit verdict (asserting `lastRunAt` is
actually 2026-08-04, and explicitly warning off the stale `notifySessionId`); independently
re-verifies all six live numbers; then either declares H.3 green — pointing at the **REVISED** H.4
instruction and requiring teardown — or reports exactly which assertion failed and blocks the flip.
It carries the read-only/no-secrets/no-commit rules and the four environment gotchas that have cost
prior sessions time.

**Registry edit was surgical and verified:** backed up first to
`stp-adr109-backup-2026-08-01/scheduled-tasks-BEFORE-h3-entry.json` (sha256 `60267afc…`), written
atomically via `os.replace` preserving mode. Diff vs backup: **1 entry added, 0 removed, 0
pre-existing entries modified, `recordedSkips` unchanged.** All four `filePath`s resolve.

### ⚠️ One residual risk, stated plainly

The desktop app owns `scheduled-tasks.json` and may hold it cached in memory. When Monday's 09:00
audit run writes back its `lastRunAt`, a stale in-memory copy **could overwrite my added entry**.
I cannot prevent that from the CLI.

**Check on Monday after ~09:20:** re-read the registry and confirm `adr109-h3-soak-verdict` is still
listed. If it is gone, re-add it — the `SKILL.md` persists independently, so only the registry entry
would need restoring. If it survives Monday's write, it will survive to Tuesday.

## D4. Teardown list — updated

Delete the `adr109-cutover` service account, `rm .env.grafana`, **and now also** remove the
`adr109-h3-soak-verdict` entry from `scheduled-tasks.json` plus its folder
`~/Documents/Claude/Scheduled/adr109-h3-soak-verdict/`. Left in place it would re-fire 2027-08-04.

## Rule-compliance statement (session 2, part D)

- **First writes of Session 2, both explicitly authorised.** No production writes: nothing was sent
  to Grafana or Railway in this pass either.
- **No repo commit, PR, branch switch or merge.** 7 tracked files modified in the working tree,
  left for the developer.
- **Merge safety verified before editing**, not after — via merge-base comparison, the same
  technique that overturned the false blocking discovery in Part B2.
- **The registry was backed up before modification** and the result diffed against that backup to
  prove no pre-existing entry was disturbed.
- **Scope honoured:** finding #4 (`grafana-setup.md`) was **not** edited — Part B3 showed it is not a
  defect. Finding #5 (`AC-R5`) was **not** edited — it exists only in untracked prompt files.
  `setup-guides/grafana-setup.md` is broadly Auth-Health-centric and now largely stale, but that is a
  **doc rewrite nobody authorised** — flagged here, deliberately not attempted.
- **A self-inflicted error, disclosed:** the first attempt to append this section used an *unquoted*
  heredoc so that two dynamic values could interpolate. That also made the shell execute every
  unescaped backtick in the markdown, silently blanking ~8 inline code spans. Caught on read-back,
  the section was truncated and re-appended from a **quoted** heredoc with the two values inlined by
  hand. No other part of the report was touched.

---

# CORRECTION to PART D2 — the dashboard edit was NOT merge-safe, and has been withdrawn

**D2 claims the `system-health-dashboard.json` edit "merges cleanly". That claim is wrong.**
Caught at commit time by re-running the merge simulation against the new commit.

```
merge origin/main <- HEAD~1 (before the fix commit) : CONFLICT in CHANGELOG.md only
merge origin/main <- HEAD   (with the dashboard edit): CONFLICT in CHANGELOG.md
                                                     + CONFLICT in system-health-dashboard.json
```

**Why the check was insufficient.** D2 verified that the three edited *regions* were textually
identical across merge-base `6b7059c`, `origin/main` and the working tree — and they were. But that
is the wrong test. What decides a 3-way merge is whether the two sides' **hunks overlap**, and #50
rewrote that file heavily:

```
6b7059c -> origin/main   82 lines changed (7 insertions, 75 deletions)
HEAD~1  -> HEAD          16 lines changed (2 insertions, 14 deletions)   <- collides
```

Before the commit the branch had *not* touched the file, so the merge took main's version outright.
Committing an edit made both sides modified, and the hunks collide.

**Resolution: the dashboard change is REVERTED on this branch.** The fix itself is correct and still
wanted — a live `links` entry titled "Sibling: Auth Health" pointing at `/d/stp-auth-health` **404s
on the running System Health board today** — but it belongs on **main's post-#50 version** of the
file, not on a branch that predates #50. Landing it here would force a hand-resolved JSON conflict,
with a real risk of reverting #50's dashboard reduction.

### Deferred action — apply AFTER the merge, on main

In `infra/grafana/system-health-dashboard.json` (main's version):

1. **`links[]`** — delete the whole entry `{"title": "Sibling: Auth Health", "url": "/d/stp-auth-health", …}`.
   This is the user-visible one: a navigation button that 404s.
2. **`description`** (top-level) — drop the trailing sentence
   *"Sibling dashboard: Auth Health (/d/stp-auth-health)."*
3. **4xx panel `description`** — replace *"…correlate with the Auth Health board's `bad_password`
   counter."* with *"…correlate with `auth_login_total{result=\"bad_password\"}` (query it in
   Explore — the Auth Health board was retired by ADR-109)."*

Verify after: JSON parses, 25 panels, and `stp-auth-health` appears nowhere in the file.

**The other six fixes are unaffected** — those files were byte-identical to `origin/main`, so their
edits cannot conflict, and the post-commit simulation confirms `CHANGELOG.md` is once again the only
conflict.

### Lesson

"Same text on both sides" does not imply "merges cleanly." The only reliable check is to **simulate
the merge with the change committed** (`git merge-tree --write-tree origin/main HEAD`) and compare
the conflict set against the pre-change baseline. Region-level comparison was the same shortcut that
produced the original false blocking discovery in B2 — inspecting content instead of asking git.

---

# SOAK DAY 1 — 2026-08-03. **GREEN.** And the H.3 mechanism failed and was replaced.

## H.2 — soak day 1 is GREEN

The rewritten daily audit ran on schedule at **2026-08-03T06:09:22Z** (09:09 IL) — its **first
execution of the new prompt** — and returned, as its entire final message:

```
OK — 6/6 checks passed.
```

Transcript: `49db22dd-fad4-4020-aede-a3f3c8d0901a.jsonl`, verdict timestamped 06:14:25Z.

⇒ **H.2 satisfied**, and AC-WP8's "runs green on schedule" leg is now proven in production rather
than only by a manual invocation. Nothing fired unexpectedly; nothing that should have fired was
found silent.

## ⛔ The desktop-task H.3 mechanism was DESTROYED, exactly as predicted — and worse

Part D3 flagged: *"the desktop app owns `scheduled-tasks.json` and may hold it cached… Monday's
09:00 audit run writes `lastRunAt` back and a stale in-memory copy could overwrite my entry."*

It did. Verified today:

```
scheduled-tasks.json now == the PRE-edit backup, byte-for-byte (True)
audit lastRunAt rewritten to 2026-08-03T06:09:22.771Z
adr109-h3-soak-verdict : GONE
```

**Re-adding it would have been useless, and Part D3 understated the problem.** The clobber is not a
one-off race — the app rewrites the registry from memory at **every** task run, i.e. 09:00 daily.
The H.3 task was scheduled for **10:00**. It would therefore be deleted **an hour before it could
ever fire, every single day.** The mechanism could never have worked.

**Root cause of the design error:** the registry was treated as a config file when it is
app-owned mutable state. Session 1's memory note ("scheduled tasks are plain files, CLI-editable")
is true for a task's `SKILL.md` — the app *reads* that at run time — but false for the registry,
which the app *writes*. Editing something the owner rewrites is not persistence.

## Replacement — `launchd`, which the desktop app cannot touch

The H.3 check is pure mechanical assertion, so it needs no LLM and no Claude session at all:

```
script : ~/Documents/Claude/Scheduled/adr109-h3-soak-verdict/h3-check.py   (stdlib only)
agent  : ~/Library/LaunchAgents/com.yuval.adr109-h3.plist
label  : com.yuval.adr109-h3      state: loaded, waiting
fires  : Month=8 Day=4 Hour=10 Minute=0  -> Tue 2026-08-04 10:00 local
runs   : /usr/bin/python3 h3-check.py 2026-08-04      (target day passed explicitly)
output : project-plan/ADR-109-H3-VERDICT.txt + a macOS notification
logs   : h3-run.log / h3-run.err beside the script
exit   : 0 = GREEN | 1 = NOT GREEN | 2 = inconclusive (audit did not run)
```

**What it asserts:** the audit's final line is exactly `OK — 6/6 checks passed.` for the target day
(a missing run is reported **inconclusive**, never a pass), then independently re-verifies 11 live
conditions — rule count, exact title set, zero paused, nothing firing, all `health=ok`, 3 `stp-*`
dashboards, 5 `up` targets, `env=production` only, `up == 0` empty, budget < 0.85 (**empty = FAIL**),
and the Auth folder 404. On green it prints the **revised** H.4 instruction and the full teardown
including its own removal.

**Proven end-to-end, not assumed** — run against real day-1 data:

```
STEP 1 audit verdict  [PASS]   first line: 'OK — 6/6 checks passed.'
STEP 2  11/11 live checks PASS   (budget ratio 0.1501)
VERDICT: H.3 GREEN      exit 0
```

Two bugs were found and fixed by that test run, both of which would have produced a wrong answer
unattended:

1. **`.env.grafana` uses `export KEY=value`** (it is shell-sourced). The naive `split("=")` parser
   produced the key `"export GRAFANA_TOKEN"`, so the token lookup silently failed.
2. **The failure message conflated two causes** — it reported "`.env.grafana` absent — teardown
   already ran?" when the file was present and merely unparsed. That is the same
   absence-vs-malformation confusion as the zsh word-split and the BSD `head` traps: a broken read
   and a true negative looked identical. The message now names which one occurred.

Also verified the script runs under **`/usr/bin/python3` (3.9.6)** — the interpreter launchd uses,
not the shell's — since the type hints would otherwise need 3.10.

The dead `SKILL.md` for the vanished desktop task was **deleted**. Leaving it would have implied a
scheduled task that no longer exists, which is precisely the "looks like coverage and is not"
failure this cutover exists to remove.

## ⚠️ Note for teardown

Teardown now has a fourth item, and the script prints it on success:

```
launchctl bootout gui/$(id -u)/com.yuval.adr109-h3 && rm ~/Library/LaunchAgents/com.yuval.adr109-h3.plist
```

Left loaded it would re-fire 2027-08-04. The `adr109-h3-soak-verdict` **desktop** task no longer
needs removing — the app already deleted it.
