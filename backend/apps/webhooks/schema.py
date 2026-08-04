"""drf-spectacular post-processing hook (M04 AC-04-14).

The webhook receiver is a plain Django view mounted outside ``/api/v1`` (no JWT
layer), so drf-spectacular's view introspection never sees it. This hook injects
the path into the generated schema by hand, documenting the in-body secret-auth
model (ADR-042) with an empty ``security`` list (JWT does not apply).
"""
from __future__ import annotations

_WEBHOOK_PATH = "/hooks/v1/{user_id}/{strategy_id}/"


def add_webhook_path(result, generator, request, public, **kwargs):
    paths = result.setdefault("paths", {})
    paths[_WEBHOOK_PATH] = {
        "post": {
            "operationId": "webhook_ingest",
            "tags": ["webhooks"],
            "summary": "TradingView webhook ingest (secret-authenticated in body).",
            "description": (
                "Public endpoint mounted outside `/api/v1` — no JWT auth. "
                "Authentication is a constant-time match of the static bearer "
                "`sig` secret embedded in the alert body (see ADR-042). "
                "Hardened with a per-user rate limit (before body read), a 16 KB "
                "body cap, `application/json`-only, 24h idempotency, and a halt gate."
            ),
            "security": [],
            "parameters": [
                {
                    "name": "user_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "format": "uuid"},
                },
                {
                    "name": "strategy_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "format": "uuid"},
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["strategy", "action", "symbol", "qty", "order_type", "sig"],
                            "properties": {
                                "strategy": {"type": "string"},
                                "action": {"type": "string", "enum": ["buy", "sell", "exit"]},
                                "symbol": {"type": "string"},
                                "qty": {"type": "number"},
                                "order_type": {"type": "string", "enum": ["MKT", "LMT"]},
                                "limit_price": {"type": "number"},
                                "sig": {"type": "string", "description": "Static bearer secret."},
                                "idempotency_key": {"type": "string"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": {"description": "Accepted / duplicate / halted (see body)."},
                "400": {"description": "Invalid JSON or schema validation failure."},
                "401": {"description": "Missing/invalid secret (generic — no oracle)."},
                "413": {"description": "Payload exceeds 16 KB."},
                "415": {"description": "Content-Type is not application/json."},
                "429": {"description": "Per-user rate limit exceeded."},
                "503": {"description": "Webhook ingest disabled by ops."},
            },
        }
    }
    return result
