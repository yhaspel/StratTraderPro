"""Impersonation token minting + session lifecycle (M10 §6.2 / AC-10-7).

Read-only, time-boxed, MFA-gated, fully audited. The token is a simplejwt access
token whose ``user_id`` claim is the TARGET so existing owner-scoped views resolve
to the target automatically; the write-block + revocation live in
``apps.users.authentication.ImpersonationAwareJWTAuthentication``.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken


def _ttl_minutes() -> int:
    return int(getattr(settings, "IMPERSONATION_TTL_MINUTES", 15))


class ImpersonationToken(AccessToken):
    """15-min access-only token; ``purpose="impersonation"``. No refresh."""

    token_type = "access"  # noqa: S105 — simplejwt token-class identifier

    def __init__(self, token=None, verify=True):
        self.lifetime = timedelta(minutes=_ttl_minutes())
        super().__init__(token=token, verify=verify)


def mint_token(session) -> str:
    token = ImpersonationToken()
    token["user_id"] = str(session.target_id)  # owner-scoped views resolve to target
    token["purpose"] = "impersonation"
    token["session_id"] = str(session.id)
    token["actor_id"] = str(session.actor_id)
    return str(token)


def start_session(*, actor, target, reason, request=None):
    """Create the session, emit the audit row, mint the token."""
    from apps.audit.events import AuditEventType
    from apps.audit.services import _client_ip, emit

    from .metrics import ADMIN_IMPERSONATION_SESSIONS
    from .models import ImpersonationSession

    now = timezone.now()
    ip = _client_ip(request) if request is not None else None
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:512] if request is not None else ""
    session = ImpersonationSession.objects.create(
        actor=actor,
        target=target,
        reason=reason[:255],
        started_at=now,
        expires_at=now + timedelta(minutes=_ttl_minutes()),
        ip=ip,
        ua=ua,
    )
    ADMIN_IMPERSONATION_SESSIONS.inc()
    emit(
        AuditEventType.ADMIN_IMPERSONATION_STARTED,
        actor=actor,
        user=target,
        request=request,
        entity_type="impersonation_session",
        entity_id=str(session.id),
        data_after={"target": str(target.id), "reason": reason},
    )
    return session, mint_token(session)


def stop_session(session, *, actor=None, request=None) -> bool:
    """Idempotent stop → immediate revocation (authentication rechecks is_active)."""
    from apps.audit.events import AuditEventType
    from apps.audit.services import emit

    if session.ended_at is not None:
        return False
    session.ended_at = timezone.now()
    session.save(update_fields=["ended_at"])
    emit(
        AuditEventType.ADMIN_IMPERSONATION_STOPPED,
        actor=actor or session.actor,
        user=session.target,
        request=request,
        entity_type="impersonation_session",
        entity_id=str(session.id),
        data_after={"target": str(session.target_id)},
    )
    return True
