# Contributing to StratTraderPro

Thanks for your interest! StratTraderPro is open-source, self-hosted software (Apache-2.0).
Contributions come as **fork-and-pull-request** — you don't need any access to the repository.

By contributing you agree that your contribution is licensed under the project's Apache-2.0
licence (see `LICENSE`).

## Before you start

- For anything non-trivial, **open an issue first** to discuss the approach — it saves you from
  building something that won't be merged.
- Check `SECURITY.md` for how to report vulnerabilities **privately** (do not open a public issue
  for a security bug).
- Be excellent to each other — see `CODE_OF_CONDUCT.md`.

## Pull Request process

1. **Fork** the repo and create a branch from `main`: `feature/<short-name>` or `fix/<short-name>`.
2. Get it running locally: `make setup && docker compose up -d --build` (see the README).
3. Make your changes. Add tests. Ensure the suite passes locally:
   ```bash
   cd backend && pytest && ruff check . && bandit -r apps config
   cd ../frontend && npx ngc --noEmit -p tsconfig.app.json && npx ng build
   ```
4. Fill in the PR template; address every applicable checklist item.
5. Open the PR against `main`. **CI must be green before it can merge.** Fork PRs run without
   secrets and may require maintainer approval to run.
6. A maintainer reviews and squash-merges. Keep PRs focused — one concern per PR.

## Code style

### Backend (Python)
- Format with `ruff format`; lint with `ruff check`; security-scan with `bandit`.
- Test with `pytest` — aim for ≥ 80% coverage on new code.

### Frontend (Angular / TypeScript)
- Standalone components only (no NgModules).
- Angular control flow (`@if`, `@for`, `@switch`).
- Use `inject()`, not constructor injection. Components inject facades, never core services directly.
- All user-facing strings go through `ngx-translate` (`en.json`).

## i18n rules

- Never hard-code user-facing strings.
- Frontend: add keys to `src/assets/i18n/en.json`.
- Backend: wrap strings with `_()` from `django.utils.translation`.

## Commit messages

Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.

## Changelog

Add an entry to `CHANGELOG.md` under `[Unreleased]` with your PR.

## A note on scope

StratTraderPro deliberately ships **zero preloaded strategies** and takes no money — these are
load-bearing choices (see `project-plan/PIVOT-TO-OSS.md` §7). PRs that add a curated strategy
catalogue, a paid tier, hosted-service features, or that would have the project touch users' broker
keys or infrastructure are **out of scope** and won't be merged.
