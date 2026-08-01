# Postmortem template

Copy this file to `docs/postmortems/YYYY-MM-DD-<short-slug>.md` and fill it in after
any real incident (every `critical` page that reflected an actual failure — not an
expected/intentional kill-switch trip). **Blameless:** the goal is to understand the
system and prevent recurrence, never to assign fault. Describe what happened and why
the system allowed it, not who "should have" done something.

See `docs/runbooks/incident-triage.md` for what pages; the alert thresholds are
the ones committed in `infra/grafana/alerts/alert-rules.yaml`.

---

# Postmortem — <title>

**Date of incident:** YYYY-MM-DD
**Author:** <name>
**Status:** Draft | Final
**Severity:** <SEV — e.g. money/trust-critical, degraded, minor>
**Related alert(s):** <e.g. WebhookErrorRatioCrit, AuditIntegrityFailure>

## Summary

Two or three sentences a reader can absorb in ten seconds: what broke, who/what was
affected, for how long, and how it was resolved.

## Impact

- **User/trading impact:** what could and couldn't happen during the window (orders
  rejected? fills missed? positions un-flattened? audit trust frozen?).
- **Duration:** detection → mitigation → full resolution (with timestamps, UTC).
- **Threshold impact:** which alert threshold was breached, by how much and for
  how long (`alert-rules.yaml`) — e.g. webhook 5xx ratio, flatten p99.
- **Data integrity:** any data lost, corrupted, or needing reconciliation.

## Timeline (UTC)

| Time | Event |
|---|---|
| HH:MM | <first symptom / alert fired> |
| HH:MM | <detected — page acknowledged> |
| HH:MM | <diagnosis / key finding> |
| HH:MM | <mitigation applied — e.g. platform halt engaged> |
| HH:MM | <resolved> |
| HH:MM | <verified recovered> |

## Root cause

The single technical reason the incident occurred. Trace it to the code path /
config / infra fact that made it possible. Link the ADR or runbook that covers the
area.

## Contributing factors

Conditions that made the incident more likely, harder to detect, or worse than it
had to be — e.g. a missing alert, a gap in a runbook, a manual step that was skipped,
an operator-deferred service that wasn't provisioned, a threshold set too loose.

## Detection

How did we find out? (Alert? Manual? A user?) Was detection fast enough? If the
alert existed but was too slow / too noisy / missing, say so — that's an action item.

## Response — what went well, what didn't

- **Went well:** the runbook that worked, the automation that stopped the bleeding.
- **Didn't:** the wrong turn, the missing tool, the ambiguous step.

## Action items

Each item: an owner, a concrete verifiable outcome, and a due date. Prefer fixes
that make the class of incident impossible or auto-detected over "be more careful."

| # | Action | Owner | Verify (done when…) | Due |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

## Lessons

What this taught us about the system that we didn't know before. If it belongs in an
ADR or a runbook, note where it was written down (and do write it down — a lesson
not committed to a doc is a lesson relearned).
