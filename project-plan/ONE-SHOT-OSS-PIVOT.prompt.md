# ONE-SHOT — OSS pivot: verify, publish, harden

**For:** Claude CLI, run from the repo root on the host machine.
**Prerequisite:** Cowork has completed WP-1 … WP-7 and left branch `chore/oss-pivot` committed
but **not pushed**. If that branch does not exist, **HALT** and say so — do not improvise the
content work.

**Spec:** `project-plan/PIVOT-TO-OSS.md` (revision 2). Read it first. It is the source of truth;
this prompt only covers the tail (WP-8, WP-9) that Cowork's sandbox cannot run.

**Why this is the CLI's job:** the sandbox has no Docker, no full Angular/Python toolchain, and
no GitHub credentials. Everything below needs at least one of the three.

---

## Rules

- Do not weaken any gate to make it pass. If a gate fails, **fix the code**, or halt and report.
- Do not `git push --force`, do not rewrite history. **D2: the 104-commit history is kept.**
- Do not flip the repo public until every gate in Phase 1 is green **and** Phase 2 §3 is done.
- Report progress after each phase. Halt on any BLOCKER.

---

## Phase 1 — Verification gauntlet (WP-8)

### 1.1 Local CI parity — all five gates

This project's CI runs more than pytest. Running only pytest and declaring victory is a known
past failure. Run **all five**:

```bash
cd backend
pytest                                   # 1
ruff check .                             # 2
bandit -r apps config                    # 3

cd ../frontend
npx ngc --noEmit -p tsconfig.app.json    # 4  ← REQUIRED
npx ng build                             # 5
```

⚠️ Gate 4 is not optional and `tsc --noEmit` is **not** a substitute — it does not catch
NG5002/NG9 template errors. WP-2 edits `frontend/src/assets/i18n/en.json`; a broken key
reference surfaces here and nowhere else.

Expect `backend/config/test_alert_rules.py` to still pass — it hard-requires
`infra/grafana/alerts/*.yaml` and `infra/grafana-agent/agent.yaml`. **If it fails, `infra/` was
deleted in error.** Per D5, `infra/grafana*` must be kept. Restore it and re-run.

### 1.2 Clean-clone boot — the actual deliverable

This is the one thing the whole pivot rests on: **can a stranger clone this and run it?**
Nobody has ever verified it end-to-end.

```bash
rm -rf /tmp/stp-clean
git clone --branch chore/oss-pivot . /tmp/stp-clean
cd /tmp/stp-clean

make setup                               # WP-4: must generate SECRET_KEY + FERNET_KEK
docker compose up -d --build             # NOT `make up` — see below
sleep 45

curl -sf localhost:8777/healthz  || { echo "BLOCKER: backend down"; exit 1; }
curl -sf localhost:8777/readyz   || { echo "BLOCKER: db/redis not ready"; exit 1; }
curl -sf localhost:4444          || { echo "BLOCKER: frontend down"; exit 1; }
echo "CLEAN-CLONE OK"
```

Then confirm WP-4 actually fixed `make up` (it used to pull in the `tunnel` profile and start an
ngrok container that errors without `NGROK_AUTHTOKEN` — the first thing a stranger would see):

```bash
docker compose down -v && make up && sleep 30
docker compose ps --format '{{.Name}} {{.State}}' | grep -iv running || echo "all services running"
```

**AC:** every service `running`. No container in a restart loop. No ngrok unless explicitly
requested via `make tunnel`.

### 1.3 Prod-settings boot from generated secrets

`prod.py` hard-crashes on `SECRET_KEY`, `FERNET_KEK`, `DATABASE_URL`, and 400s every request if
`ALLOWED_HOSTS` is empty. Confirm `make setup`'s output is genuinely sufficient:

```bash
cd /tmp/stp-clean/backend
set -a && source .env && set +a
DJANGO_SETTINGS_MODULE=config.settings.prod \
  ALLOWED_HOSTS=localhost \
  DATABASE_URL=postgres://stp_user:stp_local_pw@localhost:5432/strattraderpro \
  python -c "import django; django.setup(); print('PROD SETTINGS OK')"
```

**AC:** no `ImproperlyConfigured`. If `FERNET_KEK` is missing or the SHA-derived dev default is
rejected, WP-4 is incomplete → halt.

### 1.4 Public-repo safety sweep

Re-run the checks Cowork ran, against the **post-edit** tree, to confirm WP-3/WP-7 landed:

```bash
git grep -niE 'yuval3000@gmail|yuval3000\.grafana|up\.railway\.app|grafanacloud-yuval3000|o4511716412489728' -- . \
  && echo "BLOCKER: personal/infra identifiers still present" || echo "identifiers clean"

git grep -niE 'proprietary|all rights reserved' -- . \
  && echo "BLOCKER: proprietary claim survives" || echo "licence claim clean"

test -f LICENSE && test -f NOTICE || { echo "BLOCKER: LICENSE/NOTICE missing"; exit 1; }

git ls-files | grep -E '\.pine$' | wc -l   # MUST be 0 — zero shipped strategies
```

Also confirm no workflow uses `pull_request_target` and every workflow declares
`permissions:` (WP-6).

### 1.5 Archive reconciliation landed (WP-3b)

The plan index must not lie after the pivot.

```bash
# Every scrapped plan actually moved, and carries a SCRAPPED banner
for f in 12-beta-and-signoff.md analysis-cost-and-business-model.md ONE-SHOT-M12.prompt.md \
         ONE-SHOT-M11-OPERATOR-TAIL.prompt.md M11-operator-cowork-prompt.md M10-cowork-followups.md; do
  test -f "project-plan/archived/$f" || echo "BLOCKER: $f not archived"
  grep -qi 'SCRAPPED' "project-plan/archived/$f" || echo "BLOCKER: $f missing SCRAPPED banner"
done
test -d project-plan/archived/debug-and-verifications || echo "BLOCKER: debug-and-verifications not archived"

# No live file (outside archived/) still points at a moved plan as if current
git grep -nE '12-beta-and-signoff|analysis-cost-and-business-model' -- project-plan ':!project-plan/archived' \
  | grep -viE '(archived/|SCRAPPED|PIVOT-TO-OSS)' \
  && echo "WARN: stale reference to an archived plan" || echo "no stale plan references"

# Trackers list the milestones that were missing pre-pivot
grep -q 'M13' project-plan/PROGRESS.md && grep -q 'M14' project-plan/PROGRESS.md \
  || echo "BLOCKER: PROGRESS.md still missing M13/M14 rows"
grep -qi 'SCRAPPED\|archived/12-beta' project-plan/PROGRESS.md \
  || echo "BLOCKER: PROGRESS.md M12 not marked scrapped"

# The two live findings were transplanted before their files were archived (WP-3c)
grep -qiE 'Appendix A|DDL' docs/runbooks/audit-integrity-failure.md \
  && echo "note: verify audit-integrity-failure.md DDL was FIXED, not just present"
```

**AC:** every archived plan has a banner and is referenced from `README.md`'s archive line;
`PROGRESS.md` + `README.md` milestone tables both list M00–M11, M13, M14; no live cross-reference
to a moved file.

**HALT** on any BLOCKER above.

---

## Phase 2 — Publish (WP-9)

Only after every Phase 1 gate is green.

### 2.1 Merge

```bash
git push -u origin chore/oss-pivot
gh pr create --fill --title "chore: pivot to open-source self-hosted"
# wait for CI green, then:
gh pr merge --squash --admin      # squashes the PR only; repo history is preserved (D2)
git checkout main && git pull
```

### 2.2 Flip public

`gh repo edit --visibility public --accept-visibility-change-consequences`

*(Or: Settings → General → Danger Zone → Change visibility.)*

### 2.3 Harden — do this immediately after flipping, not later

```bash
gh repo edit \
  --description "Self-hosted, webhook-driven algorithmic trading software. Bring your own Alpaca keys." \
  --add-topic trading --add-topic algorithmic-trading --add-topic alpaca \
  --add-topic django --add-topic angular --add-topic self-hosted
```

Then in **Settings** (these have no reliable `gh` equivalent — do them in the browser):

- **Code security:** enable **secret scanning** *and* **push protection**. Enable **Dependabot alerts**.
- **Actions → General:** set *"Require approval for **all** outside collaborators."*
  Fork PRs execute code (`pip install`, `pnpm install`, `docker compose up`) — unprivileged and
  secret-less, but you still want a human in the loop.
- **Branches:** protect `main` — require CI green before merge.

### 2.4 Tear down the service

- **Railway staging: delete.** It is the environment that most concretely says "I operate a
  service." Nothing references it after WP-3.
- **Railway production:** keep **only** if it serves nobody but you. If anyone else has an
  account on it, either delete it or delete their accounts. A running multi-user instance you
  operate is the exact thing this pivot exists to stop.
- Revoke the `RAILWAY_TOKEN` GitHub secret (`deploy-staging.yml` is deleted; the secret is now
  an unused credential sitting in a public repo's settings).

### 2.5 Final state check

```bash
gh repo view --json visibility,licenseInfo,description
gh run list --branch main --limit 1
```

**AC:** `"visibility": "PUBLIC"`, `licenseInfo` = Apache-2.0, latest `main` run green.

---

## Report back

State plainly:

1. Which of the five CI gates passed, and the clean-clone result.
2. Whether prod settings booted from `make setup` output alone.
3. Repo URL, visibility, licence.
4. What was torn down on Railway, and whether **any** instance you operate still has users on
   it other than you.
5. Anything you had to fix that this prompt did not anticipate.

**Do not** report success on any gate you skipped. If you ran four of five, say so.
