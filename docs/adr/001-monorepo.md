# ADR-001: Monorepo Structure

**Status:** Accepted
**Date:** 2026-04-16
**Decision Makers:** Yuval

## Context

We need to decide whether to use a monorepo (single repository for backend + frontend + infra) or separate repositories.

## Decision

Use a **monorepo** with the following layout:

```
strattraderpro/
├── backend/      # Django API
├── frontend/     # Angular SPA
├── docker/       # Dockerfiles, nginx config
├── docs/         # ADRs, runbooks
└── project-plan/ # Milestone specs
```

## Rationale

- **Single developer (initially):** context-switching between repos adds friction with no benefit.
- **Atomic changes:** a webhook endpoint change + its Angular form update ship in one PR.
- **Shared CI:** one workflow can build both, run integration tests, and deploy.
- **Docker-compose:** local dev mounts both `backend/` and `frontend/` from one repo.

## Consequences

- CI must be smart about running only affected jobs (path filters in GitHub Actions).
- If the team grows, we may need CODEOWNERS per directory.
- Dependabot runs for both ecosystems in one place (manageable with grouping).
