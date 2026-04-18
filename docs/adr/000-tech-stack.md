# ADR-000: Technology Stack

**Status:** Accepted
**Date:** 2026-04-16
**Decision Makers:** Yuval

## Context

StratTraderPro is a multi-tenant trading bot platform that receives TradingView webhook alerts, applies regime and sentiment analysis, and executes orders against live broker accounts. We need a tech stack that supports real-time processing, background task scheduling, and a responsive dashboard.

## Decision

### Backend
- **Python 3.12** + **Django 5.x** + **Django REST Framework** — mature, well-documented, fast development cycle.
- **Celery 5** + **Redis 7** for async tasks and scheduling (celery-redbeat for crash-safe beat).
- **PostgreSQL 16** with row-level security for tenant isolation.
- **httpx** for async HTTP (broker and market data APIs).

### Frontend
- **Angular 19** with standalone components and signals-based state management.
- **3-layer architecture:** Core (services, store) → Abstraction (facades) → Presentation (components).
- **Tailwind CSS** for styling with custom design tokens.
- **ngx-translate** for i18n.

### Infrastructure
- **Railway** for hosting (web, workers, Postgres, Redis).
- **Docker** for local dev and CI.
- **GitHub Actions** for CI/CD.

### Observability
- **Sentry** (error tracking), **Prometheus** + **Grafana Cloud** (metrics), **OpenTelemetry** (traces).

## Consequences

- Django's ORM and admin give us rapid prototyping but we'll need to optimize queries for real-time trading paths.
- Angular's signals + facade pattern keeps state management simple without RxJS BehaviorSubject complexity.
- Railway limits us to container-based deploys but Dockerfiles are portable to any platform.
- Python-based NLP (FinBERT, llama-cpp-python) runs on the same stack without a separate service.
