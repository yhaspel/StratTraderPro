# Contributing to StratTraderPro

## Branch Strategy

- `main` — protected, always deployable to staging. Requires 1 review + CI green.
- `develop` — integration branch (optional; direct PRs to `main` are fine for solo dev).
- Feature branches: `feature/<milestone>-<short-name>` (e.g. `feature/m01-jwt-auth`).

## Pull Request Process

1. Create a branch from `main`.
2. Make your changes, ensuring tests pass locally (`make test-be && make test-fe`).
3. Fill in the PR template — every checkbox in the DoD checklist must be addressed.
4. CI must be green before merge.
5. Squash-merge to `main`; the commit message should reference the issue number.

## Code Style

### Backend (Python)
- Format with `ruff format`.
- Lint with `ruff check`.
- Security scan with `bandit`.
- Test with `pytest` — aim for 90%+ coverage on new code.

### Frontend (Angular/TypeScript)
- Standalone components only (no NgModules).
- Use Angular 19 control flow (`@if`, `@for`, `@switch`).
- Use `inject()` function, not constructor injection.
- Components inject facades, never core services directly.
- All user-facing strings go through `ngx-translate` (`en.json`).

## i18n Rules

- Never hard-code user-facing strings.
- Frontend: add keys to `src/assets/i18n/en.json`.
- Backend: wrap strings with `_()` from `django.utils.translation`.

## Commit Messages

Use conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.

## Changelog

Update `CHANGELOG.md` under `[Unreleased]` with every PR.
