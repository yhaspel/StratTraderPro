"""Public webhook ingest endpoint (M04 §6.3).

Mounted OUTSIDE ``/api/v1`` so no JWT auth middleware runs — the ``sig`` bearer
secret in the body is the only credential (ADR-042). A plain Django view (not
DRF) keeps the hot path lean and gives byte-level control over the body cap.

Flow (order matters):
  1. feature flag  → 503 if WEBHOOK_V1_ENABLED is off
  2. rate limit per user_id (BEFORE body read)
  3. optional TradingView source-IP allowlist
  4. content-type + 16 KB body cap
  5. parse JSON; extract top-level "sig"
  6. load WebhookConfig(user, strategy) — unknown → generic 401 (no oracle)
  7. constant-time secret compare → else 401 (+ audit row for a known config)
  8. JSON-Schema validate (sig stripped) → else 400
  9. idempotency (cache.add SETNX, 24h) → dup → 200 {duplicate: true}
 10. halt gate → 200 {rejected: reason} + audit
 11. AlertMessage row + process_alert.delay → 200 {accepted}
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import jsonschema
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.risk.killswitch import is_blocked
from apps.strategies.models import WebhookConfig
from apps.strategies.services import decrypt_secret

from .metrics import (
    R_ACCEPTED,
    R_BAD_REQUEST,
    R_DISABLED,
    R_DUPLICATE,
    R_HALTED,
    R_RATE_LIMITED,
    R_SCHEMA_INVALID,
    R_SIG_BAD,
    WEBHOOK_LATENCY,
    WEBHOOK_RECEIVED_TOTAL,
)
from .models import AlertMessage

logger = logging.getLogger(__name__)


def _json(payload: dict, status: int) -> JsonResponse:
    return JsonResponse(payload, status=status)


def _err(code: str, message: str, status: int, **extra) -> JsonResponse:
    body = {"error": {"code": code, "message": message}}
    body["error"].update(extra)
    return _json(body, status)


def _client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _rate_limited(user_id) -> bool:
    """Fixed-window per-user counter (cache-based; works on locmem + Redis)."""
    limit = getattr(settings, "WEBHOOK_RATE_LIMIT_PER_MIN", 60)
    if limit <= 0:
        return False
    bucket = int(time.time() // 60)
    key = f"wh:rl:{user_id}:{bucket}"
    try:
        cache.add(key, 0, timeout=90)
        current = cache.incr(key)
    except ValueError:  # pragma: no cover — key evicted between add/incr
        cache.set(key, 1, timeout=90)
        current = 1
    return current > limit


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(View):
    def post(self, request, user_id, strategy_id):
        started = time.monotonic()

        if not getattr(settings, "WEBHOOK_V1_ENABLED", True):
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_DISABLED).inc()
            return _err("FEATURE_DISABLED", "Webhook ingest is disabled by ops.", 503)

        # 2. rate limit BEFORE body read
        if _rate_limited(user_id):
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_RATE_LIMITED).inc()
            return _err("RATE_LIMITED", "Too many requests.", 429)

        # 3. optional source-IP allowlist
        allowlist = getattr(settings, "WEBHOOK_IP_ALLOWLIST", []) or []
        if allowlist and _client_ip(request) not in allowlist:
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_SIG_BAD).inc()
            return _err("WEBHOOK_SIG_BAD", "Unauthorized.", 401)

        # 4. content-type + size cap
        max_bytes = getattr(settings, "WEBHOOK_MAX_BODY_BYTES", 16 * 1024)
        ctype = (request.content_type or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_BAD_REQUEST).inc()
            return _err("WEBHOOK_UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json.", 415)
        body_bytes = request.body
        if len(body_bytes) > max_bytes:
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_BAD_REQUEST).inc()
            return _err("WEBHOOK_PAYLOAD_TOO_LARGE", "Payload exceeds 16 KB.", 413)

        # 5. parse JSON
        try:
            body = json.loads(body_bytes.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("payload must be a JSON object")
        except (ValueError, UnicodeDecodeError):
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_BAD_REQUEST).inc()
            return _err("WEBHOOK_INVALID_JSON", "Body is not valid JSON.", 400)
        sig = body.get("sig")
        body_wo_sig = {k: v for k, v in body.items() if k != "sig"}

        # 6. load config — unknown user/strategy → generic 401 (no oracle)
        wc = (
            WebhookConfig.objects.select_related("user", "strategy")
            .filter(user_id=user_id, strategy_id=strategy_id)
            .first()
        )
        if wc is None:
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_SIG_BAD).inc()
            return _err("WEBHOOK_SIG_BAD", "Unauthorized.", 401)

        # 7. constant-time secret compare — encode both sides so a non-ASCII sig
        # (e.g. a smart-quote paste) yields a clean 401, not a TypeError→500 that
        # skips the SIG_BAD audit and pollutes the 5xx alert (FIX-H6).
        expected = decrypt_secret(wc.secret_encrypted)
        if not isinstance(sig, str) or not hmac.compare_digest(
            sig.encode("utf-8"), expected.encode("utf-8")
        ):
            AlertMessage.objects.create(
                user=wc.user,
                strategy=wc.strategy,
                body_json=body_wo_sig,
                idempotency_key=str(body_wo_sig.get("idempotency_key", ""))[:128],
                status=AlertMessage.Status.REJECTED,
                reject_reason="SIG_BAD",
            )
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_SIG_BAD).inc()
            logger.warning("webhook.sig_bad", extra={"user": str(user_id), "strategy": str(strategy_id)})
            return _err("WEBHOOK_SIG_BAD", "Unauthorized.", 401)

        # 8. JSON-Schema validation (sig already stripped)
        try:
            if wc.json_schema:
                jsonschema.validate(body_wo_sig, wc.json_schema)
        except jsonschema.ValidationError as exc:
            AlertMessage.objects.create(
                user=wc.user,
                strategy=wc.strategy,
                body_json=body_wo_sig,
                idempotency_key=str(body_wo_sig.get("idempotency_key", ""))[:128],
                status=AlertMessage.Status.INVALID,
                reject_reason="SCHEMA_INVALID",
            )
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_SCHEMA_INVALID).inc()
            return _err("WEBHOOK_SCHEMA_INVALID", "Payload failed schema validation.", 400, detail=exc.message)

        idem = str(body_wo_sig.get("idempotency_key", ""))[:128]

        # 9. idempotency (SETNX, 24h)
        if idem:
            ttl = getattr(settings, "WEBHOOK_IDEMPOTENCY_TTL_SECONDS", 86400)
            digest = hashlib.sha256(idem.encode("utf-8")).hexdigest()
            key = f"idem:{user_id}:{digest}"
            if not cache.add(key, "1", timeout=ttl):
                WEBHOOK_RECEIVED_TOTAL.labels(result=R_DUPLICATE).inc()
                return _json({"data": {"duplicate": True}}, 200)

        # 10. halt gate (kill-switch engine — platform / user / strategy)
        reason = is_blocked(wc.user_id, wc.strategy_id)
        if reason:
            AlertMessage.objects.create(
                user=wc.user,
                strategy=wc.strategy,
                body_json=body_wo_sig,
                idempotency_key=idem,
                status=AlertMessage.Status.REJECTED,
                reject_reason=reason,
            )
            WEBHOOK_RECEIVED_TOTAL.labels(result=R_HALTED).inc()
            return _json({"data": {"rejected": reason}}, 200)

        # 11. accept — persist + dispatch
        alert = AlertMessage.objects.create(
            user=wc.user,
            strategy=wc.strategy,
            body_json=body_wo_sig,
            idempotency_key=idem,
            status=AlertMessage.Status.RECEIVED,
        )
        from .tasks import process_alert

        process_alert.delay(str(alert.id))
        WEBHOOK_RECEIVED_TOTAL.labels(result=R_ACCEPTED).inc()
        WEBHOOK_LATENCY.observe(time.monotonic() - started)
        return _json({"data": {"accepted": True, "alert_id": str(alert.id)}}, 200)
