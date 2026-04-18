# ADR-002: Railway for Hosting

**Status:** Accepted
**Date:** 2026-04-16
**Decision Makers:** Yuval

## Context

We need an always-on hosting platform for the trading bot. Key requirements: container support, managed Postgres + Redis, persistent workers (Celery), WebSocket support, reasonable cost for 10–50 users.

## Options Considered

| Platform | Pros | Cons |
|----------|------|------|
| **Railway** | Simple setup, native Postgres/Redis plugins, persistent services, auto-deploy from GitHub | Smaller community than AWS, vendor-specific CLI |
| AWS ECS/Fargate | Full control, mature ecosystem | Complex setup, overkill for MVP, higher ops burden |
| Fly.io | Edge deployment, good DX | Redis requires external provider, less mature DB |
| Render | Simple, free tier | Worker services can be slow to cold-start |
| Heroku | Familiar, easy | Expensive for always-on workers, no native Redis persistence |

## Decision

Use **Railway** for staging and production.

## Rationale

- Dockerfiles are portable — switching to Fly, Render, or k8s later requires only config changes, not code changes.
- Railway's service model maps cleanly to our architecture: 1 web, 1 worker, 1 beat, 1 LLM-worker, Postgres, Redis.
- Auto-deploy from GitHub main branch with one-click rollback.
- Cost is predictable and reasonable for the expected scale.

## Consequences

- Must use Railway CLI or API for deploys (wrapped in GitHub Actions).
- No built-in CDN — may need Cloudflare in front for production.
- Custom domains require Railway Pro plan.
