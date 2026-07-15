# PIVOT — hosted SaaS → open-source, self-hosted

**Decided:** 2026-07-14 · **Revision 2** (validated against the codebase; supersedes rev 1 of the same date)
**Supersedes:** M12 (beta & signoff), PART F (counsel review), PART H (domain), and the hosted-service assumptions in M11.
**Status:** VALIDATED — ready to implement.

---

## 0. The decision

StratTraderPro stops being a service Yuval operates for other people and becomes software
each user clones, deploys, and runs themselves against their own Alpaca account. Yuval keeps
running a private instance — live, on his own money, which has never been the regulated part.

**Why:** operating automated execution for third parties is plausibly a regulated activity
(portfolio management / investment advice / reception-and-transmission of orders) in Israel,
the US, and the EU/UK. Disclaimers do not create an exemption. Distributing software is not
an investment service: no client relationship, no discretion exercised for anyone, no personal
data processed, no broker keys held, no orders through our infrastructure.

**Costs:** the SaaS. **Keeps:** the software, live trading, and users.

### Locked decisions

| # | Decision |
|---|---|
| D1 | **Licence: Apache-2.0.** Patent grant + `NOTICE` mechanism (needed for the vectorbt notice anyway) |
| D2 | **Keep the 104-commit history.** Scrub `HEAD`, do not squash, do not rewrite. Publish the existing repo |
| D3 | **vectorbt stays a hard dependency.** Disclose Commons Clause in `NOTICE` + README. No optional-extra refactor |
| D4 | **Keep the terms-acceptance + GDPR code.** Delete only the legal *documents*. The code is a useful feature for a self-hoster and is inert by default |
| D5 | **Keep `infra/grafana*`.** `backend/config/test_alert_rules.py` hard-requires it; deleting it breaks backend CI |
| D6 | **Live trading ships enabled-capable, disabled-by-default.** Each self-hoster flips `ENABLE_LIVE_TRADING` on their own box, trading their own money |
| D7 | **Plans are ARCHIVED, not deleted.** Follow the existing convention (`project-plan/README.md:13`, precedent `archived/04A-IBKR-Web-API.md`): move to `archived/` with a `❌ SCRAPPED` banner naming *why* and *what carried over*. **Operative legal documents (`docs/legal/`) are still DELETED** — a ToS is a live instrument, a milestone plan is a record. Different things |
| D8 | **The record stays honest.** A public "here is what I decided not to build, and why" is a credibility asset and *affirmative* evidence of deliberate avoidance — not a liability. It is also consistent with D2: these files are in the history regardless, so deleting them from `HEAD` buys nothing and costs the project record |

---

## 1. Corrections to revision 1

Rev 1 was written before the codebase was checked. Four of its claims were wrong. They are
corrected here so nobody implements against them.

| Rev 1 said | Truth | Source |
|---|---|---|
| "M13 is written but NOT merged; its test suite has never been executed" | **M13 is MERGED on `main`** (`87240a3`), with ~280 lines of gate tests (`apps/brokers/test_live_mode.py`). Live trading already works: `adapter.py:97-119` follows the account row, `live_gate.py:44-53` gates on setting AND admin DB flag. **Zero code changes needed.** `MEMORY.md` is stale | `project-plan/13-live-trading-switch.md:3` |
| "Remove the `BETA_USER_EMAILS` env var" | **It does not exist in code.** Zero references in settings, Sentry init, or any view. M12's beta plumbing was planned and never written. Deleting the plan docs is a no-op | grep |
| "Rotate the Sentry DSN" | The DSN in `bugs/BUG-004` is **truncated** (`eb4bd…`). Org + project IDs only; key not recoverable. **Nothing to rotate** | `bugs/BUG-004-…md:139` |
| "Publish from a fresh squashed commit" | **Over-cautious.** The secret scan is clean; the author email is in every commit's metadata regardless, so squashing hides nothing that matters. History is a credibility asset. → **D2** | §2 |

Also stale: my memory note that BUG-004 (nginx envsubst) left 4 of 5 `STP_CONFIG` vars
unsubstituted. **It is fixed and CI-guarded** (`docker/frontend.Dockerfile:32`, enforced by
`ci.yml:431-439` via `scripts/check_envsubst_filter.py`).

---

## 2. Verified findings

### 2a. Secret scan — CLEAN ✅

Full history, all 104 commits (`git log --all -p`, 188,773 lines).

| Checked | Result |
|---|---|
| `.env` / `.pem` / `.key` / `id_rsa` ever committed | **No.** Only `*.example` files |
| Vendor keys (AWS, Stripe, Resend, GitHub, Grafana, Slack, Google, PEM, Telegram) | **Zero hits** |
| Alpaca-shaped keys | 3 — all test fixtures (`PKTESTKEYID000000000`) |
| DB/Redis URLs with real passwords | **None** — all local-compose `stp_user:stp_local_pw` |
| `FERNET_KEK` / `SECRET_KEY` literals | **None** — all `env()`-read |
| 941 × 44-char base64 blobs | All `pnpm-lock.yaml` integrity hashes. False positive |
| Full Sentry DSN | **None** — the only one is truncated |

**Nothing needs rotating.** `.gitignore` correctly covers `.env`, `.env.*`, and the M11
load-test fixtures (per-user JWTs + TOTP secrets). `.claude/` is untracked.

### 2b. Clone-and-run — mostly works, two gaps

- ✅ `docker compose up -d --build` on a bare checkout with **no `.env`** is verified on
  every PR by `ci.yml:207-254` (`e2e-smoke`), asserting `/healthz` + frontend `:4444`.
- ✅ Dev settings require **zero** env vars. Every `env()` in `base.py`/`dev.py` has a default.
- ✅ Compose uses only public Docker Hub images. No Railway-only service. Sentry/Resend/Grafana
  are all no-ops locally.
- ✅ Frontend prod build works with zero env set (BUG-004 fixed, CI-guarded).
- ❌ **`make up` is broken from a clean clone** — it adds the `tunnel` profile → starts `ngrok`,
  which needs `NGROK_AUTHTOKEN` from a **repo-root `.env`** that the README never mentions
  (README:15 tells you to copy `backend/.env.example`, which compose does not read for
  interpolation). Non-fatal, but it is the first thing a stranger sees.
- ❌ **No key bootstrap.** Prod settings hard-crash on `SECRET_KEY`, `FERNET_KEK`, `DATABASE_URL`
  (`prod.py:30,36,76`), and **`FERNET_KEK` is not in `backend/.env.example` at all**.
- ❌ **No first-user path.** Dev uses the console email backend, so the signup verification link
  is printed into `docker compose logs backend`; and every data endpoint 403s until MFA is
  enrolled (README:48). Undocumented.

### 2c. Licences

- **No AGPL/GPL/SSPL/BSL anywhere.** `psycopg2` is LGPL-with-exceptions (harmless, used via
  import — the standard situation for every MIT-licensed Django project).
- **`vectorbt==1.0.0` is Apache-2.0 + Commons Clause** — non-OSI, and forbids *selling* the
  software (including paid hosting or paid support whose value derives substantially from it).
  It does **not** block an Apache-2.0 release (not copyleft, pip dependency, not vendored), but
  it must be disclosed, and it is a one-way door on ever monetising the backtester. → **D3**.
- Frontend is uniformly permissive (Angular MIT, rxjs Apache-2.0, etc.). **Clean.**

---

## 3. The two blockers

1. **No `LICENSE` file, and `README.md:102` says "Proprietary — all rights reserved."**
   Publishing as-is is not open source; it is publishing all-rights-reserved source with a
   Terms of Service attached, which nobody may legally fork. **This voids the entire pivot.**
2. **No secret-generation bootstrap.** A self-hoster cannot bring up a production instance:
   `FERNET_KEK` crashes on startup and is not even mentioned in `.env.example`.

Everything else below is a doc edit, a deletion, or a one-line hardening.

---

## 4. Work packages

**Owner key:** 🟦 Cowork (file edits + sandbox bash) · 🟨 CLI (needs Docker, network, GitHub auth, or the real toolchain)

### WP-1 🟦 Licence and OSS hygiene — *blocker*

| File | Action |
|---|---|
| `LICENSE` | **Create** — Apache-2.0, full text, `Copyright 2026 Yuval Haspel` |
| `NOTICE` | **Create** — Apache-2.0 NOTICE; carry the vectorbt "Apache-2.0 + Commons Clause" attribution and its no-Sell condition |
| `SECURITY.md` | **Create** — how to report a vulnerability, no bounty, best-effort response |
| `CODE_OF_CONDUCT.md` | **Create** — Contributor Covenant 2.1 |
| `README.md:100-102` | **Rewrite** `## License` → Apache-2.0 + pointer to `NOTICE` |

**AC:** `LICENSE` exists at root; no file in the tree claims the project is proprietary;
`NOTICE` names vectorbt and its Commons Clause condition.

### WP-2 🟦 README rewrite — *blocker-adjacent*

Current README is product/service copy. Rewrite as software.

| Line | Problem | Fix |
|---|---|---|
| `:3` | "Regime-aware algorithmic trading **platform**" | "Self-hosted, webhook-driven algorithmic trading **software**. You run it. You own the keys." |
| `:5` | Stack line ends "· Railway **(hosting)**" | Drop Railway — it is not part of the product |
| `:11` | Clone URL `github.com/yuval3000/strattraderpro` | **Wrong.** Actual remote is `yhaspel/StratTraderPro` |
| `:19` | `make up` (broken — see WP-4) | `docker compose up -d --build` |
| `:42-51` | `## Using the app` — marketing page, Create account, Getting started checklist | This is onboarding copy for customers. Rewrite as "First run" — including the **undocumented first-user path**: verification link appears in `docker compose logs backend`, and MFA must be enrolled before any data endpoint responds |
| `:52` | "Paper trading only — StratTraderPro **never** places live or real-money orders." | **False once self-hosted.** → "Ships with live trading **disabled**. Enabling it is your choice, on your instance, with your money, at your risk." |
| `:61` | Architecture: "Broker Adapters (**IBKR CPAPI, TradeStation**)" | **Stale.** IBKR is dead; Alpaca is the broker. → "(Alpaca · TradeStation behind a flag)" |
| `:84-88` | `## Staging` with Railway URLs | **Delete.** An environment *you* run |
| — | missing | **Add `## Disclaimer`:** not financial advice · no warranty · trading loses money · **you** are the operator and **you** are responsible · past performance does not predict future results |
| — | missing | **Add `## Self-hosting`:** bring your own Alpaca keys; Sentry / Grafana / Resend / Google OAuth are optional and off by default |

Also `frontend/src/assets/i18n/en.json` → `landing.disclaimer` carries the same false
"never places live orders" string. Fix both.

**AC:** README describes software, not a hosted service. No Railway URLs. No "never places live
orders". Disclaimer present. Clone URL correct.

### WP-3 🟦 Retire operator-era material — DELETE vs ARCHIVE

Two different actions. **Delete** the live legal instruments. **Archive** everything that is a
milestone record (→ **D7**, following `archived/04A-IBKR-Web-API.md`).

**DELETE** (operative documents / stray files — not part of the project record):

| Path | Why |
|---|---|
| `docs/legal/terms-of-service.md` | A ToS with a suspension right is the evidentiary kit of a service operator. A live legal instrument, not a record |
| `docs/legal/privacy-policy.md` | Names Alpaca/Resend/Sentry as processors "**on our behalf** under a DPA" — an admission of being the data controller. Self-hosted, **the user is the controller** |
| `MEMORY.md` | **Tracked.** Internal owner's brief — nationality, legal posture, unreviewed-code admissions |
| `_hotfix_push.sh` | Stray operational script |
| `docs/ops/` | Prod bring-up, domain purchase, Cloudflare DNS |
| `docs/oncall.md` | On-call rotation with personal email + Telegram |
| `docs/slo.md`, `docs/postmortem-template.md` | SLOs and postmortems are things a *service* has |
| `.github/workflows/deploy-staging.yml` | Only file carrying `secrets.RAILWAY_TOKEN` + a private staging URL |

⚠️ **Do NOT delete `infra/grafana*`** — `backend/config/test_alert_rules.py:93-95,172-177`
hard-requires `infra/grafana/alerts/*.yaml` and `infra/grafana-agent/agent.yaml`. Deleting it
fails backend CI. → **D5**.

`seed_terms` stores two string literals referencing the deleted legal paths
(`seed_terms.py:27-28`). Update them; nothing else reads `docs/legal/`.

**ARCHIVE** — handled in full by **WP-3b** below (milestone plans move to `archived/`, not to
`/dev/null`). `project-plan/analysis-cost-and-business-model.md` and
`project-plan/12-beta-and-signoff.md` were in rev-1's delete list; they move to **archive**
instead, because deleting the business-model doc would orphan **HIGH-05** (the open tearsheet-
disclaimer defect that WP-5 depends on by name).

**AC:** legal `docs/legal/` gone; `grep -ri "terms of service\|privacy policy\|stripe\|beta
cohort"` returns nothing in tracked files **outside `archived/`**; backend CI still green.

### WP-3b 🟦 Archive scrapped milestone plans + reconcile the trackers

The pivot voids some milestone plans. Per **D7** they move to `archived/` with a `❌ SCRAPPED
2026-07-14` banner (naming why + what carried over), and every referrer is updated. This is a
bookkeeping WP — get it wrong and the plan index lies.

**Move to `archived/` (add SCRAPPED banner to each):**

| Path | Banner must say |
|---|---|
| `project-plan/12-beta-and-signoff.md` | Premise was a private beta + prod signoff. **Carried over:** `/help` route already shipped by M10.5 (fold remaining 2 articles into WP-2); `scripts/smoke.sh` idea → WP-4; the v0.1.0-tag *idea* → WP-9 (as a public-release tag, not a prod deploy) |
| `project-plan/analysis-cost-and-business-model.md` | Stripe/paid-SaaS. **Carried over:** HIGH-05 (open, → WP-5); MED-05 (broker-ToS credential storage — *resolved by* self-hosting); **verify MED-09 (cross-user Kelly leak) and CRITICAL-04 (HMM pickle-in-DB RCE) were fixed** before trusting the archive; CRITICAL-05 "vectorbt AGPL" was factually wrong (it's Commons Clause — D3) |
| `project-plan/ONE-SHOT-M12.prompt.md` | Drives void M12. Never ran |
| `project-plan/ONE-SHOT-M11-OPERATOR-TAIL.prompt.md` | PART F (seed_terms after counsel) + PART H (buy domain, paid prod Railway) void. **Transplant PART G first → WP-3c** |
| `project-plan/M11-operator-cowork-prompt.md` | Browser-driven PARTS A–H; C/D/E/F/H void or moot |
| `project-plan/M10-cowork-followups.md` | Railway/Grafana/Sentry web-UI operator steps; done or moot |
| `project-plan/debug-and-verifications/` (whole folder) | M04 Phase-A IB-Gateway spike debug trail; died with the 2026-07-05 Alpaca pivot. ⚠️ `evidence-20260515/*.png` are **screenshots of a live IBKR account** — check for account numbers **before public** (WP-3c) |

**AMEND in place (shipped milestones — do NOT archive; rewriting a closed exit gate falsifies
history). Strike only the void legal/prod/beta sections, keep the engineering:**

| Path | Amend |
|---|---|
| `11-hardening-and-load-test.md` | Void: §7.8 draft-legal-docs lines (`:333`,`:337`), §7.9, AC-11-10, §17 counsel risk row, §2/§4/§6/§15/§18 operator-track refs. **KEEP §7.7 + the GDPR/terms code (D4)** — only swap R2→filesystem (WP-7). AC-11-14 (entrypoint dispatch) and AC-11-12 (Lighthouse miss → M14) survive |
| `13-live-trading-switch.md` | §6 **gate 4 (counsel ToS + re-accept) and gate 6 (oncall go/no-go) DIE**; gates 1/2/3/5 survive (demoted to self-hoster recommendations). §1 item 4, §2 F-6 Railway clause, §5b, §7.1–7.4 void. **AC-13-16 + AC-13-17 are shipped controls — keep, rewrite rationale.** Zero code changes |
| `strat-trader-pro.md` | **Delete §13 Monetization in full (`:863-1091`)** — Stripe/tiers/marketplace/affiliate + §13.10 regulatory checklist (Commons Clause makes it not just void but prohibited, D3). Also: §1 "multi-tenant platform / 10–50 users" premise (`:15`,`:21`), ADR-013 Stripe row (`:92`), §3.1 billing row (`:112`), §4 `billing/` app (`:220`), §12 Railway-as-product (`:838-859`), §14 R8, §15 billing week + beta week + "strategy marketplace", §18 Q1/Q6/Q7 |
| `00-scoping-and-setup.md` | **KEEP** — closed-milestone history. Optional one-line "Railway/staging refs are historical". Fix the `yuval3000/strattraderpro` → `yhaspel/StratTraderPro` remote error (`§6.1`) |
| `14-frontend-first-paint.md` | **KEEP + amend header** — Option A decided (2026-07-14), 1.2 s target held (re-justified as first-run polish); add a one-line pointer to **M15** (`15-dashboard-responsiveness.md`) for the deferred dashboard-speed levers. `<prod>` in AC-14-2/7 → CI + your own box |
| `15-dashboard-responsiveness.md` | **KEEP** — new spec (2026-07-14), the deferred dashboard-speed work parked from the M14 review. Post-OSS-release polish; not in this pivot's WPs. |
| `06A-per-symbol-regime.md` | **KEEP** — pure ML spec. Only the dead M12-roadmap pointer to it dies |

**Scrub for WP-7 (add `project-plan/` to WP-7's scrub scope — rev-1 missed it):**
`plan-progress-tracker.md:13-24` (real Railway project URL + prod/staging hostnames — the
single worst offender in the repo) and `M11-COWORK-OPERATOR-REPORT.md` (Railway env IDs +
hostnames). **Keep** both files — they're evidence — but scrub the identifiers.

**Update the trackers:**

- `project-plan/README.md` — extend the archive-convention line (`:13`) with the newly archived
  files; add a `2026-07-14 OSS pivot` note (`:14`, mirroring the `:12` broker-pivot line); mark
  M12 `❌ SCRAPPED`; **add the missing M10.5, M13, M14, M15 rows**; fix "13 milestones" →
  M00–M11 + M13 + M14 + M15; amend the DoD (no staging/Sentry/Grafana-required), the branching/release section
  (no deploy pipeline), and Ownership (fork-and-PR).
- `PROGRESS.md` — M12 row → `❌ SCRAPPED 2026-07-14 → archived/`; **add M13 (merged, inert),
  M14 (spec) and M15 (spec) rows — currently absent**; add a `The 2026-07-14 OSS pivot` section mirroring the
  existing `2026-07-05 broker pivot` one; delete the billing debt line (`:116`) and fix its
  stale "vectorbt AGPL" clause (contradicts `:105`); demote the Resend-domain item
  (`:117-118`) from "before beta" to "if you run multi-user"; correct the M11 row's `[LIVE]`
  list (SERVICE_ROLE cutover + burn-rate import are **done**; prod bring-up + R2 **void**).
- `plan-progress-tracker.md` — Phase 12 → SCRAPPED + link; close the `:576` Alpaca-eligibility
  open item; add Phase 13/14/15 sections (absent); scrub `:13-24` (above).

**AC:** every archived file has a SCRAPPED banner and appears in `README.md`'s archive line; no
tracked file outside `archived/` links to a moved plan as if it were live; `README.md` +
`PROGRESS.md` milestone tables both list M00–M11, M13, M14, M15 with correct status; backend CI green.

### WP-3c 🟦 Transplant two live findings before their files are archived

Two files slated for archival each contain a **real, unfixed problem** that would vanish
silently. Extract both into tracked issues (or `docs/`) **before** WP-3b moves the files.

1. **Broken runbook DDL — a genuine bug in a doc about to be published.** PART G of
   `ONE-SHOT-M11-OPERATOR-TAIL.prompt.md` found that `docs/runbooks/audit-integrity-failure.md`
   Appendix A's DDL is **incomplete and would break every non-audit table in production if
   applied**, and its premise ("Railway gives us one role") is factually wrong. This runbook
   ships in the public repo. **Fix the runbook or delete Appendix A** — don't archive the only
   record of the finding.
2. **Live-account screenshots.** `project-plan/debug-and-verifications/evidence-20260515/`
   holds `full-screen.png` + `gateway-screen-during-debug.png` — the live IBKR Gateway UI — and
   raw smoke logs from a real IBKR paper account. **Inspect for account numbers / usernames
   before the repo goes public.** `railway-setup-commands.md` in the same folder is Railway ops —
   scrub or drop.

**AC:** `audit-integrity-failure.md` is correct or its bad DDL removed; the two PNGs are
confirmed clear of account identifiers (or excluded from the public tree).

### WP-4 🟦 Self-hosting bootstrap — *blocker*

| Item | Action |
|---|---|
| `scripts/gen-secrets.sh` | **Create.** Emit a 64-char `SECRET_KEY` and a real url-safe-base64 32-byte `FERNET_KEK`. Print to stdout as `KEY=value` lines for pasting into `.env` |
| `Makefile` | **Add `setup`** target → runs `gen-secrets.sh`, writes `backend/.env` if absent. **Fix `up`** → drop the `tunnel` profile (plain `docker compose up -d`); ngrok stays available via the existing `make tunnel` |
| `backend/.env.example` | **Add `FERNET_KEK`** with a comment explaining it is mandatory in prod and how to generate it. Fix the stale comment at `:29` ("live keys are rejected by validation") |
| `.env.example` (repo root) | **Create** — for compose interpolation (`NGROK_AUTHTOKEN`), currently undocumented |

**AC:** from a clean clone, `make setup && docker compose up -d --build` boots; `/healthz` and
`:4444` respond; `make setup` output is sufficient to bring up prod settings without a crash.

### WP-5 🟦 Fix claims the code contradicts

| File | Fix |
|---|---|
| `backend/config/settings/base.py:408-410` | Comment says *"Live keys are rejected by validation and the Alpaca adapter hard-codes the paper endpoint."* **False since M13.** Rewrite |
| `backend/.env.example:29` | Same stale claim |
| `docs/adr/030-strategy-3-file-contract.md:9` | *"The platform also **pre-seeds a catalogue of 'system' strategies**."* The repo ships **zero** strategies (`git ls-files \| grep -c '\.pine$'` → 0) — and must keep shipping zero, because curated strategies are recommendations, and recommendations are advice. **Delete the sentence** |
| Backtest tearsheet output | **HIGH-05, still open** — tearsheets carry no financial disclaimer. Add "Simulated results are hypothetical. Past performance does not predict future results." to the generated tearsheet |

**AC:** no comment or doc in the tree asserts paper-only enforcement that the code does not
implement; no doc promises a strategy catalogue.

### WP-6 🟦 Public-repo CI hardening

| File | Fix |
|---|---|
| `.github/workflows/ci.yml`, `loadtest-canary.yml` | **Add `permissions: contents: read`** at the top. Currently absent → `GITHUB_TOKEN` inherits the repo default, which may be read/write |
| `.github/workflows/deploy-staging.yml` | Delete (WP-3) |

No workflow uses `pull_request_target`. `ci.yml` uses plain `pull_request`, so fork PRs run
**without secrets** — `SENTRY_AUTH_TOKEN` resolves to `''` and its step is guarded
(`ci.yml:167`). **No leak path.** This WP is hardening, not a hole.

**AC:** every workflow declares least-privilege `permissions`.

### WP-7 🟦 Self-hoster ergonomics

| File | Fix |
|---|---|
| `backend/config/settings/prod.py:126-151` | Without Cloudflare R2, `EXPORTS_STORAGE_READY = False` → **GDPR export jobs sit PENDING forever, silently**. `base.py:730-747` already has a working FileSystemStorage `exports` backend. **Fall back to it** instead of marking storage not-ready |
| `CONTRIBUTING.md` | Assumes a solo dev with a deploy pipeline (`main` is "always **deployable to staging**"). Rewrite for **fork-and-PR from strangers** |
| `docs/runbooks/*` | `**Audience:** SRE / platform team` and `Customer support` → "you, running your own instance". Rename `platform-halt.md` — it implies you can halt everyone's trading |
| Runbooks + `setup-guides/grafana-setup.md` | Scrub the owner's personal email, Grafana org (`*.grafana.net` / `grafanacloud-*`), the real Railway prod/staging hostnames, and the Sentry org/project IDs in `bugs/BUG-004:137-139` → placeholders |

**AC:** no personal email, no real Railway hostname, no Grafana org, no Sentry org ID in any
tracked file. Export works on a self-hosted prod instance with no R2.

### WP-8 🟨 Verification gauntlet — *CLI*

Cannot run in the sandbox: no Docker, no full toolchain.

Per the project's own CI-parity rule, **all five gates**, not just pytest:

```bash
cd backend && pytest && ruff check . && bandit -r apps config
cd frontend && npx ngc --noEmit -p tsconfig.app.json && npx ng build
```

`ngc` is required — `tsc --noEmit` does **not** catch NG5002/NG9 template errors.

Then the clean-clone test — the actual deliverable of this pivot:

```bash
git clone <repo> /tmp/stp-clean && cd /tmp/stp-clean
make setup && docker compose up -d --build
curl -sf localhost:8777/healthz && curl -sf localhost:4444 && echo CLEAN-CLONE OK
```

**AC:** all five gates green; clean clone boots and serves.

### WP-9 🟨 Publish — *CLI*

1. Push `chore/oss-pivot`, open PR, self-review against this document, merge to `main`.
2. **GitHub → Settings → General → Change visibility → Public.**
3. **Settings → Code security:** enable secret scanning **and push protection**; enable Dependabot alerts.
4. **Settings → Actions → General:** "Require approval for **all** outside collaborators."
5. **Settings → Branches:** protect `main` (require CI green).
6. Repo description + topics (`trading`, `algorithmic-trading`, `alpaca`, `django`, `angular`, `self-hosted`).
7. **Railway:** tear down **staging**. Keep production only if it serves nobody but you — otherwise tear it down too.

**AC:** repo is public, licensed, CI green on `main`, secret scanning on, staging gone.

---

## 5. Execution order and handoff

```
🟦 COWORK  ─┬─ WP-1   Licence + OSS hygiene        (blocker)
            ├─ WP-2   README rewrite               (blocker-adjacent)
            ├─ WP-3   DELETE legal instruments + stray files
            ├─ WP-3c  Transplant 2 live findings   ← BEFORE WP-3b moves their files
            ├─ WP-3b  Archive scrapped plans + reconcile trackers
            ├─ WP-4   Self-hosting bootstrap       (blocker)
            ├─ WP-5   Fix contradicted claims
            ├─ WP-6   CI hardening
            └─ WP-7   Self-hoster ergonomics (scrub scope now includes project-plan/)
                      └─→ branch `chore/oss-pivot`, committed, NOT pushed
                          ─────────── HANDOFF ───────────
🟨 CLI     ─┬─ WP-8   Verification gauntlet + clean-clone docker test
            └─ WP-9   Push, PR, merge, flip public, harden, tear down Railway
```

**Ordering constraint:** WP-3c runs **before** WP-3b (extract the findings before archiving the
files that hold them). WP-3b runs after WP-1/WP-2 so the tracker rewrites reference the final
README/LICENSE state.

**The handoff boundary is Docker + GitHub auth.** Cowork's sandbox has neither. Everything up
to and including the commit is Cowork's; everything that needs the real toolchain, a container
runtime, or credentials is the CLI's.

**Handoff artefact:** `project-plan/ONE-SHOT-OSS-PIVOT.prompt.md` — a Claude CLI prompt covering
WP-8 and WP-9, following the existing `ONE-SHOT-*` convention.

---

## 6. Out of scope / deferred

- **Making vectorbt an optional extra** (→ D3). Disclosure only. Revisit if a corporate
  self-hoster complains about the non-OSI flag.
- **Deleting the terms/GDPR code** (→ D4). It is inert by default and useful to a self-hoster
  running a multi-user instance. Only the legal *documents* go.
- **Rewriting git history** (→ D2).
- **Deleting scrapped milestone plans** (→ D7/D8). They are archived, not erased — the record
  of what was deliberately *not* built is an asset, not a liability.
- **M14 (frontend first paint).** Reviewed 2026-07-14 and **KEPT** — Option A (prerender the public
  routes) locked, the 1.2 s FCP target held (re-justified as first-run polish, not bounce/SEO, since
  there is no public demo). Not part of *this* pivot's work packages; ships on its own. The
  authenticated-dashboard speed levers (in-app skeletons, service-worker/PWA) are deferred to a
  future **M15** — see `15-dashboard-responsiveness.md`.
- **Forming an entity / licensing opinion.** Not needed for this posture. Revisit if a real
  userbase appears — at which point you'd be buying legal advice with evidence of demand in
  hand, which is a far better position than today's.

---

## 7. The four things that would drag you back into regulation

Not implementation items — standing rules. All are choices.

1. **Preloaded / curated strategies.** The repo ships **zero** today. That is your single
   biggest inducement risk, already absent. Never reintroduce it. (WP-5 removes the ADR line
   that promises one.)
2. **Taking money.** Donations are usually fine; a paid tier, hosted option, or paid support
   starts re-tripping "for compensation" — and vectorbt's Commons Clause forbids it anyway.
3. **Touching anyone's keys or infrastructure.** Never "send me your API key and I'll debug
   it." Never host an instance for a friend.
4. **Marketing it as a way to make money.** Ship the engine, not a promise.

---

## 8. What this is not

Not a retreat. A de-risked on-ramp: ship it, get users, see if anyone cares. If a real userbase
appears, *then* form an entity and get a licensing opinion. Open source does not close the
company door — it just means you don't walk through it uninsured.
