# scripts/

One-off operational and spike scripts. Not packaged, not part of the
backend or frontend builds — invoked manually by Yuval (or, eventually, a
runbook step).

Anything here that survives more than one milestone should be promoted
into `backend/apps/<app>/management/commands/` (Django management
command) so it gets covered by tests and CI.

## Current contents

| Script | Purpose | Owner milestone |
|---|---|---|
| `spike_ibkr_smoke.py` | M04 Day-1 spike — proves IB Gateway sidecar topology by placing a 1-share AAPL paper market order via `ib_insync`. See `docs/runbooks/spike-ibkr-gateway.md`. | M04 |
