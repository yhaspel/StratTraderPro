# ADR-011: Email Provider — Resend

**Status:** Accepted
**Date:** 2026-04-17
**Milestone:** M01 Auth Foundation

## Context

StratTraderPro sends transactional emails for account verification, password reset, and account lockout notifications. We need a reliable, affordable email provider with good deliverability and a simple integration path.

## Decision

We use **Resend** as the transactional email provider, integrated via **django-anymail**.

## Alternatives Considered

| Provider | Pros | Cons | Verdict |
|---|---|---|---|
| **Resend** | Modern API, excellent DX, good deliverability, generous free tier (3k emails/mo), easy DKIM/SPF setup | Newer service, smaller track record | **Chosen** |
| Postmark | Industry-leading deliverability, mature | More expensive, slightly more complex setup | Fallback option |
| Mailgun | Well-known, battle-tested | Deliverability issues on shared IPs, UI/DX dated | Rejected |
| AWS SES | Cheapest at scale | Complex setup (verification, sandbox mode), poor DX | Rejected for MVP |
| Self-hosted (Postfix) | Full control | Deliverability nightmare, maintenance burden | Rejected |

## Implementation

- `django-anymail[resend]` provides the `EmailBackend`.
- API key stored in `RESEND_API_KEY` env var (never in repo).
- Dev environment uses Django's `console` email backend (emails printed to stdout).
- Test environment uses `locmem` backend (emails captured in `django.core.mail.outbox`).
- DNS records (DKIM, SPF, DMARC) must be configured on `strattraderpro.com` before production use.

## Consequences

- Switching providers later requires only changing `EMAIL_BACKEND` and the anymail config — no template changes needed, since we use Django's standard `EmailMultiAlternatives`.
- Free tier is sufficient through MVP and early beta.
- If Resend has an outage, Postmark can be swapped in within minutes.
