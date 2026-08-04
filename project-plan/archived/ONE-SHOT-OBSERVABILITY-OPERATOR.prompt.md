# ADR-109 observability cutover — one-shot prompt for Claude Cowork

> ## ⛔ ARCHIVED — HISTORICAL. DO NOT RUN.
>
> **Never executed.** Superseded by `ONE-SHOT-ADR-109-OPERATOR-CLI.prompt.md`, which is the prompt
> that actually performed the cutover on **2026-08-02**.
>
> Every precondition below is now false: live state is **11 rules / 3 dashboards / 5 targets**, the
> `StratTraderPro Auth` folder and `auth-health-email` contact point are deleted, and both exporter
> Railway services are gone. Running this would attempt deletes against objects that no longer
> exist, re-import rules **paused** (reopening the BUG-009 blind window on a healthy system), and
> overwrite the committed report.
>
> Known factual error, for anyone mining this for reuse: the claim that
> `django_http_responses_total_by_status_total` has "no series in production" is **wrong** (it has a
> live `status="200"` series); the conclusion it supports — don't drill with `WebhookErrorRatioCrit`
> — happens to remain correct, because only `status="200"` exists so the `5..` numerator is empty.
>
> Evidence: `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`.


> Paste everything below the line into Claude Cowork. It drives the browser on a Chrome
> instance already logged into **Grafana Cloud** and **Railway**. It executes the `[LIVE]`
> operator half of the 2026-08-01 observability rightsizing — the repo half is already merged.
>
> Source of truth in the repo (`main` ≥ `5fafff0`):
> `development-plans/2026-08-01-grafana-reduced-form.md` (§3 target state, §5 operator track,
> §7 rollback, WP-8), `docs/adr/109-observability-reduced-scope.md`,
> `docs/runbooks/{alerting-setup,incident-triage,worker-metrics-scrape}.md`,
> `bugs/BUG-009-all-alert-rules-imported-paused.md`, `bugs/BUG-005-grafana-free-tier-metrics-limit.md`.

---

## MISSION

PR #50 (squash `5fafff0`) merged the **code** half of ADR-109: alert rules 18 → 9, agent scrape
jobs 7 → 5, compose exporters deleted, dashboards 6 → 3, `docs/slo.md` retired.

**Grafana Cloud and Railway still show the OLD surface** — ~23 live rules (20 code + 3 hand-made
auth rules), 6 dashboards, and two exporter Railway services that nothing scrapes any more. Your
job is to make live reality match the merged code.

Work **PART A → PART H in order.** The order is not cosmetic — three hard ordering constraints are
baked into it (RULES 3–5). PART A–G is ≈60–90 min hands-on; **PART H is a next-day close-out**, so
this is a two-day task, not one sitting.

**End state:** the provisioning API lists exactly **11** rules, all `isPaused: false`, in one folder
(`StratTraderPro`); exactly **3** dashboards; exactly **5** `up` targets, all healthy; one real
critical rule tripped *and restored*; budget rate < 0.85.

---

## INPUTS YOU NEED — ask the user before touching anything

The repo redacts every environment-specific identifier.

| Input | Why | Repo status |
|---|---|---|
| **Grafana Cloud stack URL** | every API call and UI path | placeholder `https://YOUR_ORG.grafana.net` only |
| **Prometheus datasource name** | Explore queries + rule import | docs disagree (`grafanacloud-prom` / `grafanacloud-YOUR_ORG-prom` / `grafanacloud-strattraderpro-prom`). Read it from the datasource list. Only **`grafanacloud-usage`** is a real literal name |
| **Railway project** holding `grafana-agent` + the 2 exporters | PART E | no project name/ID in repo |
| **Which inbox / Telegram chat to watch** | the PART F drill asserts delivery | placeholders only — **ask which inbox; never ask for token values** |
| **What the auth warning says and when it started** | PART A | not recorded in the repo at all |
| **Which machine/account owns the daily audit task** | PART G | not in the repo at all |

**Getting the repo files you must import** (you have a browser, not a checkout) — fetch raw:
`https://raw.githubusercontent.com/yhaspel/StratTraderPro/5fafff0/infra/grafana/alerts/alert-rules.yaml`
and the same pattern for `usage-alerts.yaml` and each `infra/grafana/*-dashboard.json`.

**Where your backup goes.** Everything you export must end up **with the user**, not in your session
sandbox — if your sandbox is ephemeral, the one artifact the whole rollback depends on evaporates
when the session ends. Download files via the browser to a named local folder
(e.g. `~/stp-adr109-backup-2026-08-01/`) **and confirm with the user that they can see the files**
before PART C deletes anything.

---

## RULES OF ENGAGEMENT (read before touching anything)

1. **This is production infrastructure, and it is the alerting system itself.** Every mistake here
   is silent by construction — a broken alert does not page you to say it is broken. Run the stated
   verification after every change.
2. **Never trust a self-report (BUG-009 / BUG-011).** A rule reporting `health: ok` proves nothing —
   *a rule that never evaluates never reports a problem; the clean bill of health is produced by the
   defect.* A Railway service showing "Online" proves nothing. Assert end-to-end effects.
3. ⛔ **Un-pause gate (BUG-009).** Converter-imported rules arrive **PAUSED**, and the UI does not
   show `isPaused` anywhere. Re-run the PART C.2 gate after *every* import. **From import until the
   gate returns clean, production has zero working alerting** — including the dead-man's pair. Keep
   that window as short as possible and do nothing else inside it.
4. ⛔ **Agent-before-exporters (plan D-R8).** PART E redeploys `grafana-agent` **before** the
   exporter services are deleted. Reverse it and `up == 0` ⇒ `TargetDown` pages **critical**.
5. ⛔ **Triage-before-delete.** PART A triages the auth warning **before** PART C/D delete the auth
   rules and the Auth Health dashboard. Delete first and you have silenced an unread warning by
   accident and destroyed the dashboard you would triage it with.
6. **Ask the user to confirm before:** deleting the two **Railway services** (irreversible, PART E.3);
   deleting the **`StratTraderPro Auth` folder** and **`auth-health-email`** contact point (PART C.3);
   and **un-pausing** for the first time (RULE 3 — un-pausing a live trading platform's rules starts
   sending real pages). Screenshot the *before* state each time.
7. **STOP and report — do not improvise — if:** any verification returns something other than what
   is stated; you see any `env` value other than `production`; the paused list will not clear; an API
   call returns a status you were not told to expect; or you are unsure which of two UI elements to
   click.
8. **Do not delete metrics to fix a budget number** (BUG-005). Check `scrape_interval: 60s` FIRST —
   halving the interval doubles the bill without adding a series.
9. **Send `X-Disable-Provenance: true` on EVERY provisioning write** (`POST`, `PUT`, `DELETE`). A
   write without it stamps the object `provenance: api` and Grafana renders it **read-only**, which
   you then cannot undo through the UI.
10. **Never** paste secrets into chat or logs. **Never** set `ENABLE_LIVE_TRADING=true`.
11. **Do not touch, in either direction:** `scrape_interval: 60s`; the `MetricsPipelineDown` /
   `TargetDown` pair (CI-guarded by `DeadMansSwitchTests`); `contact-points.yaml` /
   `notification-policy.yaml` and the `operator-email` / `operator-telegram` receivers;
   `BACKEND_TARGET` / `METRICS_BASIC_AUTH_*` / the four task-target env vars. Never alert on
   `grafanacloud_org_metrics_billable_series`.
12. Keep a running log in the report file **as you go**, so a partial report survives an interrupted
   run. Log every deleted object with its UID and its JSON body.

### Reference — the target inventory

**The 11 rules that must remain** (9 in `alert-rules.yaml` + 2 in `usage-alerts.yaml`):

| Group | Rules |
|---|---|
| `trading-ops` | `WebhookErrorRatioWarn`, `WebhookErrorRatioCrit`, `BrokerStreamSilent`, `KillSwitchFlattenSlow` |
| `risk-and-queues` | `CeleryQueueDepthHigh`, `KillSwitchTriggered` |
| `platform-and-audit` | `AuditIntegrityFailure` |
| `observability-liveness` | `MetricsPipelineDown`, `TargetDown` ← dead-man's pair; **never** delete or pause |
| `grafana-cloud-usage` (folder `StratTraderPro`, interval 5m; imported against datasource **`grafanacloud-usage`**, *not* the Prometheus one) | `MetricsBudgetHigh`, `MetricsBudgetExhausted` |

**The 9 rules to delete live:** `OrderSubmitLatencyHigh`, `SentimentLag`, `HMMModelStale`,
`DBConnectionSaturation`, `BacktestQueueWaitHigh`, `BacktestFailureRate`, `BacktestArtifactBloat`,
`ApiErrorBudgetFastBurn`, `ApiErrorBudgetSlowBurn`. Groups `backtest-ops` and `slo-burn-rate` go.

**Plus** the 3 hand-made, cloud-only rules in `StratTraderPro Auth` — creation-time names/specs
(`CHANGELOG.md:554`, `setup-guides/grafana-setup.md:106-108`):

| Rule | Spec at creation (2026-05-01) |
|---|---|
| `auth-login-success` | success rate `< 0.95` for 5m → warning ← **the one that has been firing** |
| `auth-family-revocations` | `> 5/h` → critical |
| `auth-rate-limit-spike` | `> 10×` baseline → warning |

⚠️ Creation-time names — they may have been edited since. Confirm live titles from the API; their
**UIDs are nowhere in the repo**.

**Dashboards** — keep `stp-trading-ops` (Trading Ops), `stp-risk-ops` (Risk Ops),
`stp-system-health` (System Health). Delete Auth Health (`stp-auth-health`), Data Pipelines
(`stp-data-pipelines`), Backtest Ops (`stp-backtest-ops`) — **enumerate to confirm these UIDs**, the
deleted JSONs took them out of the repo.

**The 5 scrape jobs** that must be `up` after PART E: `backend`, `worker`, `worker-backtest`,
`beat`, `streams`.

> ⚠️ These are **grafana-agent job labels, NOT Railway service names.** Do not hunt for a Railway
> service called `worker` — in production those are `celery-worker` / `celery-beat`.
>
> ⚠️ **"production is the only environment" is UNVERIFIED.** The plan asserts staging was torn down
> 2026-07-15 citing PROGRESS.md, but **PROGRESS.md has no such record** — `PIVOT-TO-OSS.md:347`
> states only the *intent*. Repo docs dated 2026-07-13/14 still describe 14 targets (7 × 2 envs).
> PART E.2's query is the only actual proof.

**Contact points** — keep `operator-email`, `operator-telegram`. Delete `auth-health-email`.

### The console helper — use this, not bare snippets

Every check below assumes you have run this once per Grafana tab. It exists because **the naive
snippet passes vacuously**: `rules.filter(...)` returns `[]` just as happily when the fetch 401s,
when you are on the wrong stack, or when the body is an error object.

```js
async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new Error(`${opts?.method || 'GET'} ${path} → ${res.status} ${JSON.stringify(body)}`);
  return body;
}
async function rules() {
  const r = await api('/api/v1/provisioning/alert-rules');
  if (!Array.isArray(r)) throw new Error('not an array — wrong stack or no permission');
  if (r.length === 0) throw new Error('ZERO rules returned — you are almost certainly on the wrong stack');
  return r;
}
// Download a JS object as a file (copy() is a DevTools-only helper and will NOT exist for you)
function save(name, obj) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 2)], {type: 'application/json'}));
  a.download = name; a.click();
}
```

---

## PART A — Triage the auth "login success rate" warning — **DO THIS FIRST**

**Why first:** this warning has reportedly been firing since 2026-07-30, untriaged. It is one of the
3 hand-made rules PART C.3 deletes, and the dashboard you would investigate it with
(`stp-auth-health`) is deleted in PART D. Run the cutover first and you silence a live unread
warning by accident. **Silence it knowingly, or fix what it found — do not let deletion be the
resolution.**

1. **Ask the user** what the warning says and when it started. Then look: Alerting → Alert rules,
   find the firing rule (expected `auth-login-success`). Record its **title, UID, expression,
   threshold, `for`, and firing-since timestamp**. Expected expression:
   ```promql
   sum(rate(auth_login_total{result="ok"}[5m])) / sum(rate(auth_login_total[5m])) < 0.95
   ```
   **If none of the three is firing** — entirely plausible, since a 5-minute success ratio recovers
   on its own — do **not** invent a triage and do **not** skip PART A. Record all three rules'
   states, use **Alerting → History** to find when the rule fired and recovered, run steps 2–4 over
   *that* window, and report the discrepancy against what the user told you in step 0.
2. Open `/d/stp-auth-health` **while it still exists** and screenshot its panels over 14 days,
   focusing on login success rate. ⚠️ The board has only **four** panels
   (`setup-guides/grafana-setup.md:106-109`) — do not go hunting for a separate "lockout rate" panel
   and conclude the dashboard is broken when you cannot find one.
3. **Rule in or out the most likely benign explanation.** This is a single-user instance, so a
   success-*ratio* has a tiny denominator: two or three failed logins in a quiet week drag it under
   0.95 with nothing wrong. In Explore, query `auth_login_total` by `result` over 7d and check
   whether the absolute failure count is trivially small, and whether failures cluster in time
   (one person mistyping) or are spread out.
4. ⚠️ **Prometheus cannot answer the escalation questions — do not try.** `auth_login_total` carries
   exactly one label, `result`: no email, no IP, no account. For "who / from where", the evidence
   lives in the **audit chain**: `GET /api/v1/admin/audit/?event_type=auth.login_ok` and eyeball the
   `ip` column (per `docs/runbooks/incident-triage.md` "## Advisory — admin logins from a new IP"),
   plus the `AuthEvent` table for `account_locked` events.
5. **Escalation triggers — STOP and report to the user before PART C if:** one email is locked
   repeatedly from **many different IPs**; failures arrive faster than a human could type; or
   lockouts hit an account the user did not expect.

> ⚠️ **There is no runbook for this.** `docs/runbooks/user-locked-out.md` is often cited, but it is
> purely an `ACCOUNT_LOCKED` / `423` **ticket** runbook — no login-success-rate triage, no
> false-positive list, no benign/real criteria. Use it only for the lockout mechanics it does
> document (10 failures per 15-min sliding window, auto-expiring after 15 min, cleared by password
> reset). The judgement above is yours to make and to write down.

**Report:** the rule's exact definition, when it started, 7-day failure counts, your verdict
(**benign / real**) and the evidence. If benign, state plainly: *"retired knowingly under ADR-109,
and here is why it was not a real signal."*

> ⚠️ For the user, not a Cowork task: **four runbooks still point at the Auth Health dashboard**
> PART D deletes — `user-locked-out.md:45`, `password-reset-abuse.md:56`, `user-lost-mfa.md:93`,
> `prod-bootstrap.md:152`. Also `bugs/README.md:31` still records BUG-009 as "FIXED (**all 21
> live**)", wrong the moment PART C lands (target: 11). Collect these as a follow-up doc PR.

---

## PART B — O-1 Backup (before touching anything)

Nothing here is destructive. Do not skip it — **this backup is the rollback.**

1. **Alert rules** (captures cloud drift the repo does not have):
   ```js
   const all = await rules();
   save('adr109-rules-backup.json', all);
   all.length;                                              // record — expect ~23
   all.map(r => [r.title, r.uid, r.folderUID, r.isPaused]);  // record the full map
   ```
2. **Folders and contact points and the notification policy** — PART C.3 permanently deletes a
   folder and a contact point whose definitions exist **only in the cloud**
   (`contact-points.yaml` is a template with `${...}` placeholders, not the live object):
   ```js
   save('adr109-folders.json',        await api('/api/folders'));
   save('adr109-contact-points.json', await api('/api/v1/provisioning/contact-points'));
   save('adr109-policy-tree.json',    await api('/api/v1/provisioning/policies'));
   ```
3. **Dashboards** — export all **6** current JSONs from the UI (Share → Export → Save to file). The
   repo has committed versions, but **the cloud copies are the rollback truth.**
4. **Railway service config** — PART E.3 deletes two services **irreversibly**, destroying their
   image reference, env vars, region and networking. Screenshot each exporter service's **Settings**
   and **Variables** tabs now.
5. **The exporter rebuild recipe — this PR deleted it.** Rollback needs
   `worker-metrics-scrape.md` §"Provisioning the exporter services on Railway", which **no longer
   exists on `main`**. Save it from the pre-merge commit:
   `https://raw.githubusercontent.com/yhaspel/StratTraderPro/6b7059c/docs/runbooks/worker-metrics-scrape.md`
6. **The current daily-audit spec** — PART G *overwrites* it, and plan §7 item 4 requires being able
   to revert it. Open the scheduled task and **copy its existing prompt text verbatim** into the
   backup folder before changing anything.

7. **Baselines you will be asked to compare against later.** Record now, or PART F's checks have
   nothing to measure a change from:
   - the **budget rate** — in Explore, with the datasource set to **`grafanacloud-usage`**:
     `sum(grafanacloud_instance_samples_per_second) * 60 / scalar(grafanacloud_org_metrics_included_series)`
   - the current `count by (job, env) (up)` output (expect 7 series pre-cutover).

**Gate — read the backup back; do not trust the write.** Re-open each saved file: the rule JSON must
parse, contain exactly the count you logged (expect ≈23), and include the 3 `StratTraderPro Auth`
rules with their **UIDs and full bodies**. Confirm the 6 dashboard JSONs and the step-2 exports are
present and non-empty, and have the user confirm they can see them. A backup you have not opened is
not a backup.

⛔ **Nothing may be deleted anywhere in PARTS C–E until this read-back passes.** Deleting an object
whose backup you have not opened is a RULE 12 violation, not a line in the report.

**Report:** rule count before, the 3 auth rule titles + UIDs, the backup folder path, and explicit
confirmation the user can see every file.

---

## PART C — O-2 Grafana Cloud: rules

> **Note on an alternative, if the user asks.** Plan §5 O-2.1 mandates the import, and that is the
> default here — re-importing is what reconciles any hand-edits the cloud has accumulated back to the
> committed YAML, which is the ADR-102 §6 alerts-as-code invariant this whole change serves.
> A lower-risk variant exists — PR #50 *only deleted* rules, changing no expression, threshold,
> `for`, label or annotation on the 9 kept ones, so deleting the 9 retired rules in place reaches the
> same rule set while avoiding the paused-rule window (RULE 3) entirely. **Its cost is that any live
> drift stays undetected.** Take it only with the user's agreement, and only after diffing your PART B
> export against the raw YAML to show there is no drift. **Record which path you took** — it changes
> what rollback means.

1. **Import the updated rules.** Grafana Cloud → Alerting → Alert rules → **Import rules
   from a Prometheus/Mimir YAML file** → upload `alert-rules.yaml`. The four groups (`trading-ops`,
   `risk-and-queues`, `platform-and-audit`, `observability-liveness`) land in the `StratTraderPro`
   folder. Import `usage-alerts.yaml` **against the `grafanacloud-usage` datasource.**

   ⛔ **Wrong datasource is a silent-green failure.** Those two budget series exist only in
   `grafanacloud-usage`. Point them at the Prometheus datasource and they return **NoData forever** —
   the rules protecting the whole pipeline (BUG-005) sit there looking healthy and never fire.

   ⛔ **Set these two import settings BY HAND — the intuition is inverted and they are not in the
   YAML** (comment block only, `alert-rules.yaml` ~lines 86–100):

   | Rule | `noDataState` | `execErrState` |
   |---|---|---|
   | `MetricsPipelineDown` | **OK** | **Alerting** |
   | `TargetDown` | **OK** | **OK** |

   Do **not** "fix" these to `noDataState=Alerting`. `absent(X)` returns empty exactly when X is
   **present** — i.e. healthy — so Grafana reads empty as NoData and `Alerting` would make the
   dead-man's switch fire continuously while everything is fine. That was tried and caught.

2. ⛔ **BUG-009 un-pause gate** — only if you imported. Converter-imported rules arrive paused and
   carry the tell-tale label `__converted_prometheus_rule__: "true"`; the rules list does not show
   `isPaused`, and the API reports `health: ok` for a rule that has never evaluated.
   ```js
   (await rules()).filter(r => r.isPaused).map(r => r.title);   // MUST be []
   ```
   Un-pause either via each rule's **⋮ → Resume** in the UI, or — preferred for a bulk un-pause,
   and the only way to be sure you missed none — via the API:
   ```js
   for (const r of (await rules()).filter(r => r.isPaused)) {
     await api(`/api/v1/provisioning/alert-rules/${r.uid}`, {
       method: 'PUT',
       headers: {'Content-Type': 'application/json', 'X-Disable-Provenance': 'true'},
       body: JSON.stringify({...r, isPaused: false}),
     });
   }
   ```
   **Un-pause `MetricsPipelineDown` and `TargetDown` FIRST** and confirm both read
   `isPaused: false` — from the moment you imported until this gate is clean, the dead-man's switch
   is inert and nothing will tell you. Then do the rest.

   ⚠️ **Un-pausing is itself a paging event.** Any rule whose condition is already true fires on its
   next evaluation, and criticals go to email **and** Telegram. `MetricsBudgetHigh` /
   `MetricsBudgetExhausted` in particular are *expected* to fire correctly if the budget rate is
   elevated (BUG-009 Fix block, BUG-005). **A page arriving here is the system working.** Do not
   re-pause, silence or delete a rule to stop the noise — record what fired, finish the gate, and
   triage in PART F. If something pages that you cannot explain, STOP and report (RULE 7).

   Re-run the check until it is `[]`. **Do not proceed until then** — RULE 3's blind window is open.

3. **Delete the retired live objects.** **Re-enumerate first — never delete by a UID captured before
   an import** (a converter import can regenerate UIDs). Build the list by *title*:
   ```js
   const RETIRE = ['OrderSubmitLatencyHigh','SentimentLag','HMMModelStale','DBConnectionSaturation',
     'BacktestQueueWaitHigh','BacktestFailureRate','BacktestArtifactBloat',
     'ApiErrorBudgetFastBurn','ApiErrorBudgetSlowBurn'];
   const live = await rules();
   const targets = live.filter(r => RETIRE.includes(r.title));
   targets.map(r => [r.title, r.uid]);        // expect 9 — if fewer, record which are already gone
   ```
   Then delete, **each object type at its own endpoint** — they are three different APIs:
   - **Rules** (9 retired + the 3 auth rules):
     `DELETE /api/v1/provisioning/alert-rules/{uid}` with `X-Disable-Provenance: true`. Expect **204**.
   - **Contact point** `auth-health-email` — a *different* API, keyed by **receiver UID, not the
     display name**: `DELETE /api/v1/provisioning/contact-points/{receiverUID}` with
     `X-Disable-Provenance: true`. Take the receiver UID from your PART B.2 export.
     ⚠️ Grafana **refuses** if a notification-policy route still references it. **If that happens,
     STOP and report with the current policy JSON — do not repair the routing tree by hand.** That
     tree carries every critical page; one orphaned contact point is harmless, a mis-edited policy
     is not.
   - **Folder** `StratTraderPro Auth` (uid `cfkrwjgh3sxkwa`):
     `DELETE /api/folders/cfkrwjgh3sxkwa`. A non-empty folder needs `?forceDeleteRules=true` — prefer
     emptying it via the rule deletes above so you never need that flag.

   Order matters: **rules first, then contact point, then folder** — so a failed rule delete cannot
   orphan objects inside a folder you already removed.

4. **Gate — print all of it at once.** Pasting four statements into a console echoes only the last
   one, so build a single object; otherwise the two most important numbers scroll past unseen:
   ```js
   const live    = await rules();
   const folders = await api('/api/folders');
   const cps     = await api('/api/v1/provisioning/contact-points');
   const byUid   = Object.fromEntries(folders.map(f => [f.uid, f.title]));
   console.log({
     total:   live.length,                                                    // MUST be 11
     paused:  live.filter(r => r.isPaused).map(r => r.title),                 // MUST be []
     folders: [...new Set(live.map(r => byUid[r.folderUID] ?? r.folderUID))], // MUST be ['StratTraderPro']
     authFolderStillExists: folders.some(f => f.uid === 'cfkrwjgh3sxkwa'),    // MUST be false
     contactPoints: cps.map(c => c.name),        // MUST be operator-email + operator-telegram only
     titles:  live.map(r => r.title).sort(),     // MUST match the reference table
   });
   ```
   ⚠️ Three traps this closes: bare statements in a console echo **only the last one**, so the two
   numbers that matter would scroll past unseen — hence the single `console.log`. `folderUID` is an
   opaque id, so it is resolved to a **title**. And `authFolderStillExists` is checked against
   `/api/folders`, **not** the rules array — an empty folder that failed to delete is invisible to a
   rules-derived check, and the gate would read green while AC-R5 is unmet.

   Also confirm the 11 titles match the reference table exactly, and that the Alerting UI shows
   **five** rule groups in `StratTraderPro`: `trading-ops`, `risk-and-queues`, `platform-and-audit`,
   `observability-liveness`, `grafana-cloud-usage` (`alerting-setup.md:171`).

**If the count is not 11, delete nothing further. Report the actual list and STOP.**

**Report:** which path you took (import vs delete-in-place), rule count before → after, the paused
list at each stage, every UID deleted, and the final gate object.

---

## PART D — O-3 Grafana Cloud: dashboards

1. **Enumerate before deleting** — confirm the two UIDs rather than trusting them:
   ```js
   (await api('/api/search?type=dash-db')).map(d => [d.title, d.uid]);
   ```
   Delete **Data Pipelines** and **Backtest Ops** (expected `stp-data-pipelines`, `stp-backtest-ops`).
2. Delete the M01 Auth Health dashboard `/d/stp-auth-health`. Its folder, 3 rules and
   `auth-health-email` contact point should already be gone from PART C.3 — **verify, don't assume.**
3. **Re-import the 3 kept dashboards** (Dashboards → New → Import → Upload JSON). They keep their
   UIDs (`stp-trading-ops`, `stp-risk-ops`, `stp-system-health`) so they update in place.

   ⚠️ **Re-point the datasource on import — then SAVE the dashboard.** All three drive their panels
   off the `DS_PROMETHEUS` template variable, and `system-health-dashboard.json` ships it pinned to
   the placeholder `grafanacloud-YOUR_ORG-prom`, which does not exist in the real stack (the other
   two ship it unset). Accept the default and you overwrite a working dashboard with one whose every
   panel errors. Set the variable to the real Prometheus datasource **and save the dashboard** — a
   selection made at view time is *not persisted*, so an unsaved fix means the panels error again
   next time anyone opens it, including during the PART H soak. Panels erroring *between* import and
   this fix are the placeholder, not a cutover failure.

**Gate:** exactly **3** StratTraderPro dashboards. Open each:
- retitled panels render (SLO wording gone — they now read as plain targets);
- on System Health, the **"Sibling: Auth Health" dashboard link is gone from the header link chips**
  — it is a top-level `links` entry, **not a panel**, so scanning the panel grid for it will find
  nothing and tick a check you never performed. The only chip left should be **"Plan: M00.7.5b"**;
- the "Postgres / Redis / Celery — exporter follow-up" row and its "Why these panels are empty" text
  panel are gone;
- **no panel shows a datasource error.**

**Report:** the 3 surviving titles/UIDs and a screenshot of each showing no panel errors.

---

## PART E — O-4 Railway — ⛔ **ORDER MATTERS**

> Doing step 3 before step 1 pages you critically. Do not reorder. Do not batch.

1. **Redeploy `grafana-agent`** from the merged commit `5fafff0` — its config no longer has the
   exporter scrape jobs. **Wait for that deploy to reach Active and confirm from its logs that it is
   scraping**, before touching anything else.

   **Only then** delete the now-unused `POSTGRES_EXPORTER_TARGET` / `REDIS_EXPORTER_TARGET` env vars.
   ⚠️ On Railway an env-var edit triggers its own redeploy: remove them while the new build is still
   in flight and the service can restart on the **old** config, which references those vars under
   `-config.expand-env=true` and will fail to render.

2. **Wait at least 6 minutes**, then verify in Explore (Prometheus datasource). **Run both queries —
   the first is an inventory, the second is the health check, and the first cannot tell you the
   second:**
   ```promql
   count by (job, env) (up)     # inventory: exactly 5 series, env="production" only
   up == 0                      # health: MUST return no data
   ```
   - Why 6 minutes, not 2: an instant query **looks back ~5 minutes** (`alert-rules.yaml:110`), so a
     target the agent has *correctly* stopped scraping keeps returning its last sample for up to
     5 min. **Seeing 7 series before the 6-minute mark is expected, not a failed redeploy** — at
     2 min you would wrongly conclude the agent was broken and start re-deploying the one component
     whose death blinds all alerting.
   - Why both queries: `count` counts *series per group*, not health — a target that is **down**
     still has an `up` series (valued 0) and still counts 1. `count` alone reads identically whether
     all five targets are healthy or all five are dead.

   ⛔ **Any `env` value other than `production` means a second agent is still shipping metrics
   somewhere. STOP and inventory before step 3.** Likewise, if an exporter job is still listed
   **more than 6 minutes** after the redeploy, the agent did not pick up the new config — fix that
   first, and do **not** delete the exporter services to make the series go away.

3. **Only now** delete the two exporter Railway services. **Ask the user to confirm first — this is
   irreversible.**

   ⚠️ **Do not assume their names — the repo contradicts itself.** The plan, ADR-109 and
   `docs/ops/service-role-cutover.md` use the *compose* names `postgres-exporter` / `redis-exporter`,
   but `project-plan/M11-COWORK-OPERATOR-REPORT.md:90` — the only document written while looking at
   the live production Railway UI — records **`postgres-exporter-prod`** / **`redis-exporter-prod`**
   (prod services in this project carry `-prod` suffixes). **Read the actual service list and match
   it.** Confirm each is an *exporter*, not the database itself. If you cannot tell two services
   apart, STOP and ask.

   > If you are ever forced to delete first, the plan's fallback is a 1h silence on `TargetDown`
   > scoped `service=~"postgres|redis"`. That matcher is **correct**: the exporter scrape jobs
   > carried `labels: { service: postgres }` and `{ service: redis }` (agent.yaml at `6b7059c`), so
   > the anchored regex matches exactly — note it is the `service` label values, **not** the
   > `-exporter` job or Railway service names. Still prefer the ordering; the silence is the fallback.

4. Re-run **both** queries from step 2. Still exactly 5 series; `up == 0` still returns no data.
   Confirm `TargetDown` and `MetricsPipelineDown` are **not** firing.

**Report:** both queries' output before and after the deletion, and explicit confirmation the agent
redeploy preceded the deletions.

---

## PART F — O-5 Live verification

1. **Zero paused rules — again**, after everything: `(await rules()).filter(r => r.isPaused).map(r => r.title)` → `[]`.
2. `up` set correct (PART E.4), and `MetricsPipelineDown` / `TargetDown` both **Normal**.

3. **Trip real rules end-to-end** — `docs/runbooks/alerting-setup.md` Step 5.
   > **Do not test with a scratch rule.** A freshly created rule is not paused, so the drill passes
   > cheerfully while the real rules sit inert. *A test that exercises a fresh copy of the thing is
   > not a test of the thing.*

   ⚠️ **Before lowering any threshold, confirm in Explore that the rule's series actually has
   samples.** A rule whose inputs are empty evaluates to NoData → OK no matter what you set the
   threshold to — the drill then "passes" having proven nothing. This is the BUG-009 trap wearing a
   different hat.

   ⚠️ **Do NOT use `WebhookErrorRatioCrit` for this.** Its input,
   `django_http_responses_total_by_status_total`, has **no series in production** — prod has served
   zero requests through the Django middleware stack, and `/metrics` and `/healthz` bypass it
   (verified and recorded as a non-finding in `M11-COWORK-OPERATOR-REPORT.md:181`). Lowering its
   threshold cannot make it fire.

   **(a) warning → email only.** Trip **`CeleryQueueDepthHigh`**: `max(celery_queue_depth) > 1000`
   → `> -1`. This is the one reliably trippable rule — `celery_queue_depth{queue}` is refreshed
   **every 30 s by a beat task** (`apps/admin_portal/tasks.py`), so it is always present as long as
   beat and worker are alive, which this cutover requires anyway.

   **(b) critical → email + Telegram.** First check in Explore whether any `severity: critical` rule
   actually has samples. **On an idle single-user instance, probably none do:**

   | Critical rule | Why it may not be trippable |
   |---|---|
   | `WebhookErrorRatioCrit` | input has **no series in production** (see above) |
   | `BrokerStreamSilent` | `broker_stream_heartbeat_age_seconds` is labelled per `account_id` — no series unless a broker account is actively streaming |
   | `KillSwitchFlattenSlow` | `rate(..._bucket[10m])` — needs a *recent* flatten; empty when idle |
   | `KillSwitchTriggered`, `AuditIntegrityFailure` | counters awaiting their first event — no series until one occurs |
   | `MetricsPipelineDown`, `TargetDown` | ⛔ never touch — dead-man's pair |

   - **If one of them does have samples**, trip that one by lowering its threshold.
   - **If none do** (the likely case), prove the route instead of the rule: the notification policy
     matches on the **`severity` label** (`severity = critical` → `operator-telegram`,
     `continue: true` → also email). So temporarily set `severity: critical` on the
     `CeleryQueueDepthHigh` object you are already tripping, confirm **both** channels deliver, then
     restore the label. **Say in your report which of these two paths you used** — they prove
     different things: the first proves a specific rule fires, the second proves only the routing.

   Edit the **committed rule object** via the provisioning API (provisioned rules are read-only in
   the UI). Watch Inactive → Pending(activeAt) → Firing(activeAt + `for`), and confirm delivery.

   ⛔ **Restore everything you changed, byte-for-byte, and read it back.** A rule left inverted — or
   left mislabelled `critical` — fires on every evaluation, forever, to email *and* Telegram. That is
   how you teach an operator to ignore a pager. Restore from the body you stashed before editing (or
   from the PART B backup), then **re-read each rule from the provisioning API** and confirm the
   expression matches the committed YAML exactly. Tick each off individually:
   - [ ] `CeleryQueueDepthHigh` expression read back == `max(celery_queue_depth) > 1000`
   - [ ] `CeleryQueueDepthHigh` `severity` back to `warning` (if you used the label path)
   - [ ] any other rule you tripped read back == its committed expression
   - [ ] each restored rule confirmed **Inactive** and still `isPaused: false`

   **You may not leave PART F with any rule holding a modified threshold or label.** If a restore
   fails, STOP and report immediately — do not "fix" it by pausing or deleting the rule.

4. **Budget-rate check.** ⚠️ **Switch the Explore datasource to `grafanacloud-usage` first** — these
   series do not exist in the Prometheus datasource, and against the one still selected from step 2
   you will get an empty result that looks like a healthy zero:
   ```promql
   sum(grafanacloud_instance_samples_per_second) * 60 / scalar(grafanacloud_org_metrics_included_series)
   ```
   ⛔ **A blank result is a FAILED check, not a pass** — an empty result reads as "not above 0.85"
   and would record the final acceptance number having measured nothing. If it comes back empty,
   re-check the datasource selector.

   The pass condition is the absolute value: **< 0.85**. Compare against the baseline you recorded in
   PART B.7 — expect only a *small* drop, since the exporter jobs were already keep-listed to ~10
   series each. **A flat number is not evidence the deletion failed.** If high, see RULE 8 — check
   `scrape_interval` first, **do not delete metrics**.

**Report:** paused list (`[]`), the `up` set, the drill timeline with which channels received what,
**both** restore confirmations, and the budget number.

---

## PART G — WP-8: update the daily silent-failure audit spec

**Why urgent:** once PART E lands the audit will **false-alarm every morning** — it still asserts the
old shape (7 `up` targets, ~20 rules). An alarm that cries wolf daily is worse than none. (The user
reports it has been flagging stale baselines since 2026-07-29; there is no run history in the repo,
so treat the current spec as unknown until you read it.)

> ⚠️ **The audit is a Cowork scheduled task, not a repo file.** Nothing in `scripts/` or
> `.github/workflows/` implements it; it lives in the **desktop app's scheduled tasks**. **Test this
> empirically — open the scheduled-tasks list and look.** If the audit is not there, say so plainly
> and hand the user the spec below to paste in themselves. **Do not report this part as done if you
> could not open the task.**

Replace its assertion spec with:

1. Provisioning API: rule titles == exactly the **11** reference rules; `isPaused == false` for all;
   the **`StratTraderPro Auth` folder does not exist**.
2. `up{env="production"} == 1` for exactly **5** targets — `backend`, `worker`, `worker-backtest`,
   `beat`, `streams` — with **no `up` series for any other job label, and no `env` value other than
   `production`**.
3. beat → queue → worker loop fresh *(unchanged — carry the existing assertion over verbatim)*.
4. Budget rate
   `sum(grafanacloud_instance_samples_per_second) * 60 / scalar(grafanacloud_org_metrics_included_series) < 0.85` *(unchanged)*.
5. Frontend `STP_CONFIG` check *(unchanged — carry over verbatim)*.
6. Report only on failure *(unchanged)*.

> For items 3 and 5 the repo does not record the existing assertions — **copy them across unchanged
> from the PART B.6 backup**; do not invent new ones.

**Gate (AC-WP8) — prove both directions:**
- **Run it now** (do not wait for tomorrow's schedule) and confirm **green**.
- Then deliberately pause **`MetricsBudgetHigh`** for 5 minutes and confirm the audit **reports** it
  (proving it still detects the BUG-009 class). ⛔ Pause *that* rule specifically — **never**
  `MetricsPipelineDown` or `TargetDown`, which would disable the dead-man's switch, and not a
  money-path rule.
- **Un-pause it**, and re-run the PART F.1 gate.

**Report:** whether you could reach the task at all, the new spec as saved, the green run, and the
pause-drill result.

---

## PART H — Soak, then close out

⚠️ **Do not declare this done at the end of PART F.** Plan §10.6: the change closes only after **one
full trading day** on the reduced set, with **the daily audit green on day 2**.

1. Leave it running a full trading day. Watch for anything unexpectedly firing — and, more
   importantly, anything that *should* have fired and did not.
2. On day 2, confirm the audit run is green.
3. Then tell the user the two `⏳ PENDING` lines in `project-plan/PROGRESS.md:130-136` are ready to
   flip, and give them the exact wording. **That is a repo edit — you do not make it.**

---

## ROLLBACK (if anything goes wrong)

1. **Grafana Cloud rules — `POST`, not `PUT`.** A deleted rule's UID no longer exists, so
   `PUT /api/v1/provisioning/alert-rules/{uid}` returns **404**. Recreate with
   `POST /api/v1/provisioning/alert-rules` (`Content-Type: application/json`,
   `X-Disable-Provenance: true`, body = the object from `adr109-rules-backup.json`). Use `PUT` only
   for rules that still exist and merely need a field restored.
   ⚠️ Re-created/re-imported rules can arrive **paused** — run the PART C.2 gate again.
2. **Folder / contact point / policy:** recreate the folder (`POST /api/folders`), the contact point
   (`POST /api/v1/provisioning/contact-points`), and restore the policy tree
   (`PUT /api/v1/provisioning/policies`) from your PART B.2 exports.
3. **Dashboards:** re-import the 6 JSONs exported in PART B.3.
4. **Railway:** recreate the two exporter services from the PART B.4 screenshots plus the PART B.5
   copy of §"Provisioning the exporter services on Railway" — that section was deleted by PR #50 and
   exists only at `6b7059c`, so there is nothing to read on `main`. Re-add
   `POSTGRES_EXPORTER_TARGET` / `REDIS_EXPORTER_TARGET` to `grafana-agent`; redeploy the agent.
5. **Daily audit:** restore the pre-change spec from your PART B.6 copy (plan §7 item 4).
6. The repo half reverts with `git revert` of PR #50 — a developer task, not yours.

## NOT for Cowork (flag to the user, do not attempt)

- **Any repo change, commit, PR or merge.** The code half is merged (`5fafff0`). If you find
  something wrong in the YAML, report it — do not edit and push.
- **The four stale runbook pointers and the `bugs/README.md:31` BUG-009 row** (see PART A note) —
  a doc PR for the developer.
- **Flipping the `PROGRESS.md` ⏳ PENDING lines** — hand the wording to the user (PART H.3).
- **Deleting or editing `backend/apps/users/metrics.py`.** The `auth_*` counters intentionally
  survive the dashboard's deletion and stay queryable in Explore.

## FINAL REPORT

Produce one consolidated report **and hand it to the user as a file they can commit** —
`project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`, shaped like the existing
`project-plan/M11-COWORK-OPERATOR-REPORT.md`. (You do not commit it.)

For each PART A–H: **Done / Partially done / Blocked / Skipped (why)**, with verification output
quoted. Lead with:

- **PART A's verdict** on the auth warning — benign or real, with evidence. This is the one genuinely
  new piece of information in the whole run, not a checklist item.
- The headline numbers: **rules == 11 (0 paused)**, **dashboards == 3**, **`up` targets == 5, all
  healthy (`up == 0` empty)**, **budget < 0.85**.
- **Which PART C path you took** (import vs delete-in-place) — it determines what rollback means.
- Whether the drill delivered on both channels — and **which drill path you used** (a real critical
  rule, or the `severity` label flip). Do not report a warning-only drill as if it proved both
  channels.
- For **every** rule you touched: the restored expression **read back from the provisioning API**,
  matched against the committed YAML.
- Whether PART G was reachable from your session type at all.

Then list everything you STOPped on — and if you ever deleted an object whose backup you had not
read back, say so first and loudly: that is a rule violation, not a status line.
