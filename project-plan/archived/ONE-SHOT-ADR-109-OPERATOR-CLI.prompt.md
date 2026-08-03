# ONE-SHOT — ADR-109 operator cutover, PARTS B(finish) → H

> ## ✅ ARCHIVED — EXECUTED 2026-08-02. DO NOT RE-RUN.
>
> **This is the prompt that performed the ADR-109 cutover.** PARTS C–G ran in full against live
> production: 12 alert rules, a folder, a contact point, 3 dashboards and 2 Railway services were
> deleted; the alert drill fired and was confirmed on email **and** Telegram.
>
> Re-running it would try to delete objects that no longer exist and misreport the result.
> PART H (the soak) was closed out separately — see the report.
>
> Corrections found during execution (C1, C2, D1, D2) are recorded in
> `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`, which is the authoritative record.


**Run this with Claude CLI on Yuval's Mac.** It is a continuation, not a fresh start: a Cowork
cloud session already completed PART A and most of PART B on 2026-08-02 and stopped — deliberately —
at the first gate needing a human. Its report is at
`project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`. **Read that file first.**

**Nothing in production has been changed yet.** No deletes, no imports, no un-pauses, no redeploys.

---

## 0. PREREQUISITES — the human must do these before starting

The CLI has no browser. Everything below is `curl` + `jq` against the Grafana HTTP API, so it needs
a token.

1. **Create a Grafana service-account token** (once), in
   `https://yuval3000.grafana.net` → Administration → Users and access → Service accounts →
   Add service account → role **Admin** → Add service account token.
2. Export it. **Never echo it, never paste it into a report, never commit it:**
   ```bash
   export GRAFANA_URL="https://yuval3000.grafana.net"
   export GRAFANA_TOKEN="glsa_...."      # paste in your shell only
   ```
   Sanity check (must print your org, not 401):
   ```bash
   curl -sS -H "Authorization: Bearer $GRAFANA_TOKEN" "$GRAFANA_URL/api/org" | jq -r .name
   ```
3. **Railway**: be logged in (`railway login`) or have the dashboard open — PART E needs it.
4. Working dir = the repo root (`~/Documents/Claude/Projects/StratTraderPro`), on `main`, up to date
   with `origin/main` (must contain `5fafff0`).

> **Claude: if `GRAFANA_TOKEN` is unset or `/api/org` returns anything but 200, STOP and say so.
> Do not try to obtain a token yourself, and do not proceed against a stack you cannot identify.**

### Shell helpers — define these once, use them for everything

```bash
g()  { curl -sS -H "Authorization: Bearer $GRAFANA_TOKEN" "$GRAFANA_URL$@"; }
# every WRITE must carry X-Disable-Provenance, or Grafana marks the object read-only forever
gw() { curl -sS -w '\n[HTTP %{http_code}]\n' \
        -H "Authorization: Bearer $GRAFANA_TOKEN" \
        -H "Content-Type: application/json" \
        -H "X-Disable-Provenance: true" "$@"; }
rules() { g /api/v1/provisioning/alert-rules; }
```

---

## 1. CARRY-FORWARD FACTS — already verified, do NOT re-derive

Treat these as established. Re-deriving them wastes time; **contradicting** one of them means
something changed and you should STOP and report.

### Identity (the repo redacts all of this)

| | value |
|---|---|
| Stack | `https://yuval3000.grafana.net` (org "Main Org.") |
| Prometheus datasource | **name** `grafanacloud-yuval3000-prom`, **uid** `grafanacloud-prom` (isDefault) |
| Usage datasource | **name and uid** both `grafanacloud-usage` |
| Backend | `https://backend-production-f3e8.up.railway.app` |
| Frontend | `https://strattraderpro.up.railway.app` |

⚠️ `setup-guides/grafana-setup.md:67` says `strattraderpro.grafana.net`. **That host does not
resolve.** Ignore it.

### Folders — the code rules are in a NESTED subfolder

| uid | title |
|---|---|
| `fhfvn9` | **StratTraderPro** (top level, holds **no** rules directly) |
| `alerting-34szz3tqd4u0g` | **`stp-alert-rules.prom.yaml`** — subfolder of the above, **holds all 20 code rules** |
| `cfkrwjgh3sxkwa` | **StratTraderPro Auth** — holds the 3 hand-made rules |
| `dfkrcz8xo4l4we` | GrafanaCloud (Grafana's own) |

⚠️ **`GET /api/folders` returns top-level folders ONLY** — `alerting-34szz3tqd4u0g` is not in it.
Any check that maps `folderUID` against that list silently falls through to a raw uid. Resolve
subfolders with `GET /api/folders/{uid}`.

### Contact points and routing

| uid | name | action |
|---|---|---|
| `cfrr29ejep1xcc` | `operator-email` | KEEP |
| `bfrr3jmzghbeoa` | `operator-telegram` | KEEP — **settings hold a live bot token; never print or export it** |
| `bfkrwig5cgohsb` | `auth-health-email` | **DELETE** (PART C.3) |

Policy tree (captured, unchanged):
```
default → operator-email
  ├─ severity = critical          → operator-telegram   (continue: true)
  └─ severity =~ critical|warning → operator-email
group_by=[grafana_folder, alertname]  group_wait=30s  group_interval=5m  repeat_interval=4h
```
**`auth-health-email` is an orphan — no route references it**, so its delete will not be refused.
The PART C.3 "STOP if a route still references it" branch does not apply.

### Live state as of 2026-08-02 06:00 IL

- **23 rules, none paused.** 20 in `stp-alert-rules.prom.yaml`, 3 in `StratTraderPro Auth`.
- **6 `stp-*` dashboards** (plus 13 Grafana-Cloud-managed ones — Usage Insights, Cardinality
  management, Billing/Usage etc. **Those are not yours; never delete them.**
  "exactly 3 dashboards" means the `stp-*` set).
- **`up` = 5 series** — `backend`, `beat`, `worker`, `worker-backtest`, `streams`, all
  `env="production"`. `up == 0` returns no data.
- **Budget rate 0.11685**, `active_series` 1179, `included_series` 10000.
- `scrape_interval: 60s` (RULE 8 ground truth, unchanged).

### The 3 auth rules — live titles ≠ the names in the docs

| uid | live title | severity |
|---|---|---|
| `auth-login-success` | `Auth login success rate < 95%` | warning |
| `auth-family-revocations` | `Refresh family revocations > 5/hour` | critical |
| `auth-rate-limit-spike` | `Auth rate-limit hits sustained` | warning |

---

## 2. CORRECTIONS to the original ADR-109 operator prompt

The original prompt was written without access to the live stack. Three of its instructions are
wrong. **These corrections are the main reason this handoff exists.**

### ⛔ C1. Do NOT import. Delete in place.

The original mandates re-importing `alert-rules.yaml` via the Prometheus converter. **On this stack
that does not reconcile — it duplicates.** The converter names its folder after the uploaded file,
so importing `alert-rules.yaml` creates a *new* subfolder `alert-rules.yaml` and leaves
`stp-alert-rules.prom.yaml` standing with all 20 of its rules → ~31 rules across two subfolders.

The import's only stated benefit is catching hand-edit drift. **A live-vs-`5fafff0` diff was already
run: zero drift, 11/11 keepers exact** on group, `for`, `severity` and expression. So there is
nothing to reconcile, and importing would additionally:

- re-open the BUG-009 paused window (production with **zero** working alerting, including the
  dead-man's pair), and
- risk the two budget rules' datasource binding, which is **currently correct**
  (`MetricsBudgetHigh` / `MetricsBudgetExhausted` are already on `grafanacloud-usage`).

**Take the delete-in-place path: 12 `DELETE`s, no paused window at all.** Record that this is the
path taken — it changes what rollback means (rollback = `POST` the objects back, not re-import).

**Therefore PART C.2's un-pause gate is not needed** — but still *run the check* after every write
(`rules() | jq '[.[]|select(.isPaused)]|length'` must stay `0`). If anything ever comes back paused,
STOP.

### ⛔ C2. The end state keeps the nested subfolder. Do not "fix" it.

After the deletes, the 11 rules remain in `StratTraderPro / stp-alert-rules.prom.yaml`, **not**
directly in `StratTraderPro`. The original's gate (`folders MUST be ['StratTraderPro']`) is
unsatisfiable without moving every rule to `fhfvn9`.

**Do not move them.** Moving requires a `PUT` to every rule including `MetricsPipelineDown` and
`TargetDown` — the CI-guarded dead-man's pair that RULE 11 says not to touch in either direction —
and it would change the `grafana_folder` label the notification policy groups on. The folder
placement is cosmetic; the rule set is what ADR-102 §6 is about.

**Instead: accept it, and note in the report that AC-R5's wording needs amending to
`StratTraderPro/stp-alert-rules.prom.yaml`.** That is a doc fix for the developer.

### ⛔ C3. PART E.1 has already happened. Do not redeploy the agent again.

Railway auto-deployed `grafana-agent` from `5fafff0` when #50 merged. `up` already returns exactly
the 5 correct jobs and the exporter jobs are already unscraped — **in the safe order** (agent first,
exporter services still alive), so RULE 4 / plan D-R8 is satisfied.

This also **settles** the prompt's flagged uncertainty: `env="production"` is the only env value
present. "Production is the only environment" is now proven by PART E.2's own query.

What remains in PART E is only steps 1b (drop the two stale env vars) and 3 (delete the two
services). **Re-verify with the queries before you touch anything** — if `up` no longer shows 5
healthy production targets, something changed since 06:00 and you must STOP.

### C4. PART A is DONE — do not redo it, and do not let deletion be the resolution

Verdict: **BENIGN, and the rule is defective.** The live expression is not what the prompt
predicted — it wraps the denominator in `clamp_min(..., 0.0001)`, so when nobody logs in,
`0 / 0.0001 = 0 < 0.95` → **it fires on absence of traffic, not on failure**. 7-day stats: **4
logins, 0 failures, 100% success**. 479 consecutive 5-minute samples all exactly `0.0000`. One
failed login in 30 days, so a lockout is arithmetically impossible (needs 10 in 15 min).

Full evidence is in the report. **Deleting it removes a false-positive generator.** Proceed.

---

## 3. RULES OF ENGAGEMENT

1. **This is production, and it is the alerting system itself.** Every mistake is silent by
   construction. Run the stated verification after every change.
2. **Never trust a self-report.** `health: ok` proves nothing — a rule that never evaluates never
   reports a problem. "Online" in Railway proves nothing. Assert end-to-end effects.
3. **`X-Disable-Provenance: true` on EVERY write** (`POST`/`PUT`/`DELETE`). Without it Grafana
   stamps the object `provenance: api` and renders it read-only, which you cannot undo in the UI.
4. **Ask the human before:** deleting the two Railway services (irreversible); deleting the
   `StratTraderPro Auth` folder and the `auth-health-email` contact point. Show the *before* state
   each time.
5. **STOP and report — do not improvise — if:** any verification returns something other than
   stated; you see any `env` value other than `production`; any rule reports `isPaused: true`; an
   API call returns an unexpected status; or a carry-forward fact in §1 turns out to be false.
6. **Do not touch, in either direction:** `scrape_interval: 60s`; the
   `MetricsPipelineDown` / `TargetDown` pair; `contact-points.yaml` / `notification-policy.yaml` and
   the `operator-email` / `operator-telegram` receivers; `BACKEND_TARGET` / `METRICS_BASIC_AUTH_*` /
   the four task-target env vars. Never alert on `grafanacloud_org_metrics_billable_series`.
7. **Do not delete metrics to fix a budget number.** It is 0.117 — this will not come up.
8. **Never print secrets.** Not the Grafana token, not the Telegram bot token in
   `operator-telegram.settings`. **Never set `ENABLE_LIVE_TRADING=true`.**
9. **Append to the report as you go** (`project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`), so a
   partial report survives an interrupted run. Log every deleted object with its uid and JSON body.
10. **No repo commits, PRs or merges.** The code half is merged. If you find something wrong in the
    YAML, report it — do not edit and push. The report file itself is for the human to commit.

---

## STEP 0 — close the PART B backup gate. **BLOCKING.**

The cloud session could not read `~/Downloads` and therefore could not read its own backup back.
Its ⛔ still binds: **nothing may be deleted until this passes.** You *can* read `~/Downloads`.

```bash
BK=~/Documents/Claude/Projects/StratTraderPro/stp-adr109-backup-2026-08-01
mkdir -p "$BK"
mv ~/Downloads/adr109-*.json "$BK"/ 2>/dev/null
ls -la "$BK"
```

Then **actually open them** — a backup you have not opened is not a backup:

```bash
for f in "$BK"/*.json; do
  printf '%-58s %8s bytes  ' "$(basename "$f")" "$(wc -c <"$f")"
  jq -e . "$f" >/dev/null && echo "parses OK" || echo "*** PARSE FAIL ***"
done
echo "--- rule count in the full export (expect 23) ---"
jq 'length' "$BK/adr109-rules-backup.json"
echo "--- the 3 auth rules must be present with full bodies ---"
jq -r '.[]|select(.folderUID=="cfkrwjgh3sxkwa")|"\(.uid)  \(.title)  paused=\(.isPaused)"' \
   "$BK/adr109-rules-backup.json"
echo "--- integrity of the auth-rules subset already verified by the cloud session ---"
shasum -a 256 "$BK/adr109-auth-rules-backup.compact.json"
# MUST be: 198a04755c04bc299c48f0f5bd3268d2ac4d21641741a23da26c440da02818eb
```

**Required to proceed:** `adr109-rules-backup.json` parses and contains **23** rules including the
3 auth rules with full bodies, **and** all **6** dashboard JSONs
(`stp-trading-ops`, `stp-risk-ops`, `stp-system-health`, `stp-auth-health`, `stp-data-pipelines`,
`stp-backtest-ops`) are present and non-empty.

**If any of the six dashboard JSONs is missing, re-export it before continuing** — the three being
deleted were removed from the repo by #50, so **the cloud copy is the only copy**:

```bash
for u in stp-trading-ops stp-risk-ops stp-system-health stp-auth-health stp-data-pipelines stp-backtest-ops; do
  g "/api/dashboards/uid/$u" | jq . > "$BK/adr109-dashboard-$u.json"
  echo "$u -> $(wc -c <"$BK/adr109-dashboard-$u.json") bytes"
done
```

Also still missing from PART B and worth capturing now:

- **B.4** — screenshots of each exporter service's **Settings** and **Variables** tabs in Railway
  (needed to rebuild them; deletion destroys image ref, env vars, region, networking).
- **B.5** — the exporter rebuild recipe, deleted by #50 and existing only pre-merge:
  ```bash
  git show 6b7059c:docs/runbooks/worker-metrics-scrape.md > "$BK/worker-metrics-scrape-6b7059c.md"
  grep -n "Provisioning the exporter services" "$BK/worker-metrics-scrape-6b7059c.md"
  ```
- **B.6** — the **current** daily-audit task prompt, copied verbatim (PART G overwrites it, and
  reverting requires the original). See PART G.

> ⛔ **Do not proceed past STEP 0 until the read-back passes.** Deleting an object whose backup you
> have not opened is a rule violation, not a line in the report.

---

## PART C — rules 23 → 11 (delete-in-place)

### C.1 Enumerate by title and confirm the arithmetic

```bash
RETIRE='["OrderSubmitLatencyHigh","SentimentLag","HMMModelStale","DBConnectionSaturation","BacktestQueueWaitHigh","BacktestFailureRate","BacktestArtifactBloat","ApiErrorBudgetFastBurn","ApiErrorBudgetSlowBurn"]'
rules() { g /api/v1/provisioning/alert-rules; }
rules() > /tmp/live.json 2>/dev/null || rules > /tmp/live.json
jq --argjson r "$RETIRE" '
  {total: length,
   retire: [.[]|select(.title as $t | $r|index($t))|{title,uid,ruleGroup}],
   auth:   [.[]|select(.folderUID=="cfkrwjgh3sxkwa")|{title,uid}],
   paused: [.[]|select(.isPaused)|.title]}' /tmp/live.json
```

**Expect:** `total: 23`, `retire` = **9** entries, `auth` = **3** entries, `paused` = `[]`.
`23 − 9 − 3 = 11`. If `retire` has fewer than 9, record which are already gone and do not
substitute guesses. **If any count differs, STOP.**

### C.2 Delete — rules first, then contact point, then folder

Order matters: a failed rule delete must not orphan objects inside a folder you already removed.

```bash
# 12 rules: 9 retired + 3 auth. Log the full body BEFORE each delete (RULE 9).
for uid in $(jq -r --argjson r "$RETIRE" \
      '.[]|select((.title as $t | $r|index($t)) or .folderUID=="cfkrwjgh3sxkwa")|.uid' /tmp/live.json); do
  jq --arg u "$uid" '.[]|select(.uid==$u)' /tmp/live.json >> "$BK/deleted-rule-bodies.jsonl"
  echo "--- DELETE $uid"
  gw -X DELETE "$GRAFANA_URL/api/v1/provisioning/alert-rules/$uid"   # expect 204
done
```

```bash
# contact point — keyed by RECEIVER UID, not display name
gw -X DELETE "$GRAFANA_URL/api/v1/provisioning/contact-points/bfkrwig5cgohsb"   # expect 202/204
```
> If Grafana refuses because a policy route references it: **STOP and report with the current
> policy JSON.** Do not repair the routing tree by hand — that tree carries every critical page.
> (It should not refuse; the point was verified orphaned.)

```bash
# folder — should now be empty, so no forceDeleteRules flag needed
gw -X DELETE "$GRAFANA_URL/api/folders/cfkrwjgh3sxkwa"
```

### C.3 Gate — print it all at once

```bash
rules > /tmp/after.json
echo '{'
echo "  total:  $(jq 'length' /tmp/after.json)                 # MUST be 11"
echo "  paused: $(jq -c '[.[]|select(.isPaused)|.title]' /tmp/after.json)   # MUST be []"
echo "  folderUIDs: $(jq -c '[.[]|.folderUID]|unique' /tmp/after.json)"
echo "     # MUST be exactly [\"alerting-34szz3tqd4u0g\"]  (see correction C2 — nested subfolder)"
echo "  authFolderStillExists: $(g /api/folders | jq '[.[]|select(.uid=="cfkrwjgh3sxkwa")]|length>0')   # MUST be false"
echo "  contactPoints: $(g /api/v1/provisioning/contact-points | jq -c '[.[].name]')"
echo "     # MUST be exactly operator-email + operator-telegram"
echo "  titles: $(jq -c '[.[].title]|sort' /tmp/after.json)"
echo '}'
```

`titles` must be exactly:
`AuditIntegrityFailure, BrokerStreamSilent, CeleryQueueDepthHigh, KillSwitchFlattenSlow,
KillSwitchTriggered, MetricsBudgetExhausted, MetricsBudgetHigh, MetricsPipelineDown, TargetDown,
WebhookErrorRatioCrit, WebhookErrorRatioWarn`

Also confirm in the UI that `StratTraderPro/stp-alert-rules.prom.yaml` shows **five** groups:
`trading-ops`, `risk-and-queues`, `platform-and-audit`, `observability-liveness`,
`grafana-cloud-usage`.

**If the count is not 11, delete nothing further. Report the actual list and STOP.**

---

## PART D — dashboards 6 → 3

```bash
g "/api/search?type=dash-db&query=" | jq -r '.[]|select(.uid|startswith("stp-"))|"\(.uid)  \(.title)"'
```
Expect the 6 `stp-*` boards. **Only ever touch `stp-*` uids.**

```bash
for u in stp-data-pipelines stp-backtest-ops stp-auth-health; do
  test -s "$BK/adr109-dashboard-$u.json" || { echo "NO BACKUP for $u — STOP"; break; }
  gw -X DELETE "$GRAFANA_URL/api/dashboards/uid/$u"
done
```

### Re-import the 3 keepers — and **save** the datasource fix

All three drive panels off the `DS_PROMETHEUS` template variable, and
`system-health-dashboard.json` ships it pinned to the placeholder `grafanacloud-YOUR_ORG-prom`,
which does not exist. **A selection made at view time is not persisted** — you must save it, or the
panels error again for the next viewer, including during the PART H soak.

Do it via the API so the fix is durable, substituting the real uid:

```bash
for f in trading-ops risk-ops system-health; do
  jq --arg ds "grafanacloud-prom" '
    .dashboard = (. as $root | .) |
    walk(if type=="object" and .uid? and (.uid|type=="string") and (.uid|test("YOUR_ORG")) then .uid=$ds else . end)
  ' "infra/grafana/$f-dashboard.json" > /tmp/$f.json 2>/dev/null || cp "infra/grafana/$f-dashboard.json" /tmp/$f.json
  jq -n --slurpfile d /tmp/$f.json \
     '{dashboard: $d[0], overwrite: true, message: "ADR-109 cutover: re-import + pin DS_PROMETHEUS"}' \
     > /tmp/$f.payload.json
  gw -X POST "$GRAFANA_URL/api/dashboards/db" -d @/tmp/$f.payload.json
done
```
> Inspect the templating block first — if the `DS_PROMETHEUS` input is structured differently from
> what the `walk` above assumes, fix it explicitly rather than trusting the substitution. Then
> **open each board and confirm no panel shows a datasource error.**

**Gate — exactly 3 `stp-*` dashboards.** On each, verify:
- retitled panels render, SLO wording gone;
- on **System Health**, the "Sibling: Auth Health" link is gone from the **header link chips** —
  it is a top-level `links` entry, **not a panel**, so scanning the panel grid will find nothing and
  tick a check you never performed. Only **"Plan: M00.7.5b"** should remain;
- the "Postgres / Redis / Celery — exporter follow-up" row and its "Why these panels are empty"
  text panel are gone;
- **no panel shows a datasource error.**

---

## PART E — Railway. **ORDER MATTERS. Step 1 is already done (correction C3).**

### E.1 Re-verify before touching anything

```bash
PROM="/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query"
g "$PROM?query=$(printf 'count by (job, env) (up)' | jq -sRr @uri)" \
  | jq -r '.data.result[]|"\(.metric.job)/\(.metric.env)=\(.value[1])"'
g "$PROM?query=$(printf 'up == 0' | jq -sRr @uri)" | jq '.data.result|length'
```
**Required:** exactly 5 series — `backend`, `beat`, `worker`, `worker-backtest`, `streams` — all
`env=production`; `up == 0` returns `0` results.

⛔ **Any `env` other than `production` ⇒ a second agent is shipping metrics somewhere. STOP and
inventory.** ⛔ If an exporter job is still listed, the agent did **not** pick up the new config —
fix that first, and **do not delete the exporter services to make the series go away.**

### E.2 Drop the two stale env vars on `grafana-agent`

Remove `POSTGRES_EXPORTER_TARGET` and `REDIS_EXPORTER_TARGET`. An env-var edit triggers its own
redeploy — wait for it to reach Active and confirm from the logs that it is still scraping.

### E.3 Delete the two exporter services — **ASK THE HUMAN FIRST. IRREVERSIBLE.**

⚠️ **Do not assume the names.** The plan, ADR-109 and `docs/ops/service-role-cutover.md` use the
compose names `postgres-exporter` / `redis-exporter`, but
`project-plan/M11-COWORK-OPERATOR-REPORT.md:90` — the only doc written while looking at the live
Railway UI — records **`postgres-exporter-prod`** / **`redis-exporter-prod`**. **Read the actual
service list and match it.** Confirm each is an *exporter*, not the database itself. **If you cannot
tell two services apart, STOP and ask.**

> Fallback if you are ever forced to delete first: a 1h silence on `TargetDown` scoped
> `service=~"postgres|redis"`. That matcher is correct — the exporter scrape jobs carried
> `labels: {service: postgres}` / `{service: redis}` — note it matches the **`service` label
> values**, not the `-exporter` job or Railway service names. Prefer the ordering; the silence is
> the fallback.

### E.4 Re-run both queries from E.1

Still exactly 5 series; `up == 0` still empty. Confirm `TargetDown` and `MetricsPipelineDown` are
**not** firing.

---

## PART F — live verification and the alert drill

### F.1 Zero paused, after everything
```bash
rules | jq -c '[.[]|select(.isPaused)|.title]'    # MUST be []
```

### F.2 Dead-man's pair both Normal
```bash
g /api/prometheus/grafana/api/v1/rules \
  | jq -r '.data.groups[].rules[]|select(.name=="MetricsPipelineDown" or .name=="TargetDown")|"\(.name) \(.state) \(.health)"'
```

### F.3 Trip a real rule end-to-end

> **Do not test with a scratch rule.** A fresh rule is not paused, so the drill passes cheerfully
> while the real rules sit inert. *A test that exercises a fresh copy of the thing is not a test of
> the thing.*

⚠️ **Before lowering any threshold, confirm in Explore that the rule's series actually has samples.**
An empty input evaluates to NoData → OK regardless of threshold, and the drill "passes" having
proven nothing.

⚠️ **Do NOT use `WebhookErrorRatioCrit`.** Its input
`django_http_responses_total_by_status_total` has **no series in production** — prod has served zero
requests through the Django middleware stack, and `/metrics` and `/healthz` bypass it (recorded as a
non-finding in `M11-COWORK-OPERATOR-REPORT.md:181`). Lowering its threshold cannot make it fire.

**(a) warning → email only.** Trip **`CeleryQueueDepthHigh`**: `max(celery_queue_depth) > 1000` →
`> -1`. It is the one reliably trippable rule — `celery_queue_depth{queue}` is refreshed **every
30 s by a beat task** (`apps/admin_portal/tasks.py`), so it is present as long as beat and worker
are alive, which this cutover requires anyway.

**(b) critical → email + Telegram.** First check whether **any** `severity: critical` rule has
samples. On an idle single-user instance, probably none do:

| Critical rule | Why it may not be trippable |
|---|---|
| `WebhookErrorRatioCrit` | input has no series in production (above) |
| `BrokerStreamSilent` | labelled per `account_id` — no series unless a broker account is streaming |
| `KillSwitchFlattenSlow` | `rate(..._bucket[10m])` — needs a *recent* flatten; empty when idle |
| `KillSwitchTriggered`, `AuditIntegrityFailure` | counters awaiting their first event |
| `MetricsPipelineDown`, `TargetDown` | ⛔ never touch — dead-man's pair |

- **If one has samples**, trip that one.
- **If none do** (likely), prove the *route* instead: temporarily set `severity: critical` on the
  `CeleryQueueDepthHigh` object you are already tripping, confirm **both** channels deliver, then
  restore the label.

**Say in the report which path you used** — they prove different things. Do not report a
warning-only drill as if it proved both channels.

Edit via the provisioning API (`PUT /api/v1/provisioning/alert-rules/{uid}` with
`X-Disable-Provenance: true`). **Stash the exact original body first:**
```bash
rules | jq '.[]|select(.title=="CeleryQueueDepthHigh")' > /tmp/celery-original.json
```
Watch Inactive → Pending(activeAt) → Firing(activeAt + `for`), and confirm delivery.

### F.4 ⛔ Restore byte-for-byte and read back

A rule left inverted — or left mislabelled `critical` — fires on every evaluation, forever, to email
*and* Telegram. That is how you teach an operator to ignore a pager.

```bash
UID=$(jq -r .uid /tmp/celery-original.json)
gw -X PUT "$GRAFANA_URL/api/v1/provisioning/alert-rules/$UID" -d @/tmp/celery-original.json
rules | jq -r '.[]|select(.title=="CeleryQueueDepthHigh")
        |"expr: \(.data[0].model.expr)\nsev:  \(.labels.severity)\npaused: \(.isPaused)"'
```
Tick each off individually:
- [ ] `CeleryQueueDepthHigh` expression reads back == `max(celery_queue_depth) > 1000`
- [ ] `CeleryQueueDepthHigh` `severity` back to `warning` (if you used the label path)
- [ ] any other rule you tripped reads back == its committed expression
- [ ] each restored rule confirmed **Inactive** and still `isPaused: false`

**You may not leave PART F with any rule holding a modified threshold or label. If a restore fails,
STOP and report immediately — do not "fix" it by pausing or deleting the rule.**

### F.5 Budget rate — **against `grafanacloud-usage`, not the Prometheus datasource**

```bash
Q='sum(grafanacloud_instance_samples_per_second) * 60 / scalar(grafanacloud_org_metrics_included_series)'
g "/api/datasources/proxy/uid/grafanacloud-usage/api/v1/query?query=$(printf '%s' "$Q" | jq -sRr @uri)" \
  | jq -r '.data.result[0].value[1] // "EMPTY"'
```
⛔ **`EMPTY` is a FAILED check, not a pass** — an empty result reads as "not above 0.85" and would
record the final acceptance number having measured nothing.

Pass condition: **< 0.85**. Baseline before the cutover was **0.11685**. Expect only a small drop —
the exporter jobs were already keep-listed to ~10 series each. **A flat number is not evidence the
deletion failed.**

---

## PART G — WP-8: the daily silent-failure audit spec

**Why urgent:** the audit still asserts the old shape (7 `up` targets, ~20 rules) and has been
flagging stale baselines since 2026-07-29. Once this cutover lands it will **false-alarm every
morning**. An alarm that cries wolf daily is worse than none.

⚠️ **The audit is a Cowork *desktop-app* scheduled task named `strattraderpro-silent-failure-audit`.
It is NOT in the repo** (nothing in `scripts/` or `.github/workflows/` implements it) **and it is NOT
in the cloud scheduled-task list** — the Cowork session checked and found 8 unrelated triggers.

**Test this empirically: open the desktop app's scheduled-tasks list and look.** If you cannot reach
or edit it from the CLI, **say so plainly and hand the human the spec below to paste in themselves.
Do not report this part as done if you could not open the task.**

**Before overwriting, copy the existing prompt verbatim to `$BK/daily-audit-prompt-BEFORE.md`** —
reverting requires it, and items 3 and 5 below must be carried across from it unchanged.

### Replacement assertion spec

1. Provisioning API: rule titles == exactly these **11** —
   `AuditIntegrityFailure, BrokerStreamSilent, CeleryQueueDepthHigh, KillSwitchFlattenSlow,
   KillSwitchTriggered, MetricsBudgetExhausted, MetricsBudgetHigh, MetricsPipelineDown, TargetDown,
   WebhookErrorRatioCrit, WebhookErrorRatioWarn`;
   `isPaused == false` for all; the **`StratTraderPro Auth` folder does not exist**
   (check `/api/folders`, not the rules array — an empty folder that failed to delete is invisible
   to a rules-derived check).
2. `up{env="production"} == 1` for exactly **5** targets — `backend`, `worker`, `worker-backtest`,
   `beat`, `streams` — with **no `up` series for any other job label, and no `env` value other than
   `production`**.
3. beat → queue → worker loop fresh — *carry over verbatim from the BEFORE copy.*
4. Budget rate
   `sum(grafanacloud_instance_samples_per_second) * 60 / scalar(grafanacloud_org_metrics_included_series) < 0.85`
   — and treat an **empty result as FAIL**, not as a healthy zero.
5. Frontend `STP_CONFIG` check — *carry over verbatim from the BEFORE copy.* (Note the URL must be
   `strattraderpro.up.railway.app`; the old `frontend-production-c977f` 404s.)
6. Report only on failure.

> **Also fix, while you are in there:** CHECK 5's DPM ratio band. `active_series` fell from ~6,946
> to ~1,179 after the OSS pivot, so the same jitter swings the old `samples_per_second*60/active_series`
> ratio ~5× further (observed 0.76–1.18 against a documented "healthy" 0.85–0.96). Prefer a
> `query_range` over a few hours rather than an instant value, or widen the band. A real regression
> looks like BUG-005's — a sustained ~2×, not oscillation around 1.

### Gate (AC-WP8) — prove both directions

- **Run it now** (do not wait for tomorrow) and confirm **green**.
- Then deliberately pause **`MetricsBudgetHigh`** for 5 minutes and confirm the audit **reports** it
  (proving it still detects the BUG-009 class).
  ⛔ Pause *that* rule specifically — **never** `MetricsPipelineDown` or `TargetDown`, which would
  disable the dead-man's switch, and not a money-path rule.
- **Un-pause it**, and re-run the PART F.1 gate.

---

## PART H — soak, then close out

**Do not declare this done at the end of PART F.** Plan §10.6: the change closes only after one full
trading day on the reduced set, with the daily audit green on day 2.

1. **The next US trading day is Monday 2026-08-03.** Sunday is not a soak.
2. Watch for anything unexpectedly firing — and, more importantly, **anything that should have fired
   and did not.**
3. On day 2, confirm the audit run is green.
4. Then tell the human the two `⏳ PENDING` lines in `project-plan/PROGRESS.md:130-136` are ready to
   flip, and give the exact wording. **That is a repo edit — you do not make it.**

---

## ROLLBACK

1. **Rules — `POST`, not `PUT`.** A deleted rule's uid no longer exists, so
   `PUT /api/v1/provisioning/alert-rules/{uid}` returns **404**. Recreate with
   `POST /api/v1/provisioning/alert-rules` (`Content-Type: application/json`,
   `X-Disable-Provenance: true`, body from `adr109-rules-backup.json` or
   `deleted-rule-bodies.jsonl`). Use `PUT` only for rules that still exist and need a field restored.
   ⚠️ Re-created rules can arrive **paused** — re-run the paused check.
2. **Folder / contact point / policy:** recreate the folder (`POST /api/folders` with
   `uid: cfkrwjgh3sxkwa`, title `StratTraderPro Auth`), the contact point
   (`POST /api/v1/provisioning/contact-points`), and restore the policy tree
   (`PUT /api/v1/provisioning/policies`) from `$BK`.
   ⚠️ The contact-point backup in `$BK` from the cloud session is a **redacted inventory**, not a
   restorable export — but `auth-health-email` is a plain email receiver to `yuval3000@gmail.com`
   with `singleEmail: false`, which is fully specified there.
3. **Dashboards:** re-import the 6 JSONs in `$BK`.
4. **Railway:** recreate the two exporter services from the B.4 screenshots plus
   `$BK/worker-metrics-scrape-6b7059c.md` §"Provisioning the exporter services on Railway" (deleted
   by #50, exists only at `6b7059c`). Re-add `POSTGRES_EXPORTER_TARGET` / `REDIS_EXPORTER_TARGET`
   and redeploy the agent.
5. **Daily audit:** restore from `$BK/daily-audit-prompt-BEFORE.md`.
6. The repo half reverts with `git revert` of PR #50 — a developer task, not yours.

---

## NOT FOR THIS RUN — flag to the human

- **Any repo change, commit, PR or merge.**
- **The `clamp_min` defect.** `auth-login-success` is being deleted so it is moot for that rule, but
  **grep for `clamp_min` in any other ratio denominator** — wherever the pattern appears, idleness
  reads as 100% failure.
- **Four runbooks still point at the Auth Health dashboard** PART D deletes:
  `user-locked-out.md:45`, `password-reset-abuse.md:56`, `user-lost-mfa.md:93`,
  `prod-bootstrap.md:152`.
- **`bugs/README.md:31`** records BUG-009 as "FIXED (**all 21 live**)" — already wrong (23), wrong
  differently after PART C (11).
- **`setup-guides/grafana-setup.md:67`** gives a stack host that does not resolve.
- **AC-R5 wording** — should say `StratTraderPro/stp-alert-rules.prom.yaml` (correction C2).
- **Audit-log IP attribution is inconsistent** — `Login succeeded` / `Oauth login ok` record the real
  client IP, but `Refresh ok` / `Logout` / `Mfa challenge ok` record AWS edge IPs, i.e. a proxy hop
  is losing `X-Forwarded-For` on some paths. Matters to any future "logins from a new IP" advisory,
  which is exactly what `docs/runbooks/incident-triage.md` tells an operator to use.
- **Deleting or editing `backend/apps/users/metrics.py`** — the `auth_*` counters intentionally
  survive the dashboard's deletion and stay queryable in Explore.

---

## FINAL REPORT

**Append to `project-plan/ADR-109-COWORK-OPERATOR-REPORT.md`** (do not rewrite PART A/B — they are
done and their evidence stands). Add a "PARTS C–H — CLI continuation" section. Do not commit it.

For each of PARTS C–H: **Done / Partially done / Blocked / Skipped (why)**, with verification output
quoted. State explicitly:

- **rules == 11 (0 paused)**, **`stp-*` dashboards == 3**, **`up` targets == 5, all healthy
  (`up == 0` empty)**, **budget < 0.85**;
- **which PART C path you took** — it should be delete-in-place; if you deviated, say why;
- **whether the drill delivered on both channels, and which drill path you used** (a real critical
  rule, or the `severity` label flip);
- **for every rule you touched:** the restored expression **read back from the provisioning API**,
  matched against the committed YAML;
- **whether PART G was reachable at all** from a CLI session;
- every uid you deleted.

Then list everything you STOPped on — and **if you ever deleted an object whose backup you had not
read back, say so first and loudly:** that is a rule violation, not a status line.

---

## What the CLI cannot do — hand these back to the human

1. **Confirm Telegram receipt** in PART F.3(b). There is no Telegram access here. Ask Yuval to watch
   the chat during the drill and confirm; report the leg as **unverified** if he does not.
2. **Screenshots** (PART B.4 Railway tabs, PART D dashboard panels). Describe what to capture and
   have him do it, or verify the equivalent via API/DOM and say which you did.
3. **The two irreversible Railway service deletions** and the `StratTraderPro Auth` folder /
   `auth-health-email` deletions — these need his explicit go-ahead (RULE 4).
