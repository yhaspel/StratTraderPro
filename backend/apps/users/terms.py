"""Terms of Service / Privacy Policy versioning + acceptance (M11 §7.8)."""
from __future__ import annotations

from .models import TermsAcceptance, TermsDocument


def current_versions() -> dict:
    """Current in-force ToS + Privacy versions (or empty strings if unset)."""
    tos = TermsDocument.current(TermsDocument.Kind.TERMS)
    privacy = TermsDocument.current(TermsDocument.Kind.PRIVACY)
    return {
        "tos_version": tos.version if tos else "",
        "tos_url": tos.url if tos else "",
        "privacy_version": privacy.version if privacy else "",
        "privacy_url": privacy.url if privacy else "",
    }


def _latest_acceptance(user):
    return TermsAcceptance.objects.filter(user=user).order_by("-accepted_at").first()


def acceptance_state(user) -> dict:
    """Current versions + whether ``user`` must (re)accept.

    ``needs_acceptance`` is True when a document of either kind is in force and the
    user's most recent acceptance does not match the current version pair. If no
    documents are configured yet, acceptance is never required (the flow is inert
    until legal content is seeded).
    """
    cur = current_versions()
    has_docs = bool(cur["tos_version"] or cur["privacy_version"])
    latest = _latest_acceptance(user)
    if not has_docs:
        needs = False
    elif latest is None:
        needs = True
    else:
        needs = (
            latest.tos_version != cur["tos_version"]
            or latest.privacy_version != cur["privacy_version"]
        )
    return {**cur, "needs_acceptance": needs}


def record_acceptance(user, *, tos_version: str, privacy_version: str, ip: str | None) -> TermsAcceptance:
    """Persist an acceptance row + audit event + metric."""
    from apps.audit.services import emit

    from .metrics_gdpr import TERMS_ACCEPTANCES_TOTAL

    row = TermsAcceptance.objects.create(
        user=user,
        tos_version=tos_version,
        privacy_version=privacy_version,
        ip=ip,
    )
    # Keep the profile's convenience mirror in sync (used by legacy checks).
    try:
        profile = user.profile
        profile.terms_version_accepted = tos_version
        profile.save(update_fields=["terms_version_accepted"])
    except Exception:  # noqa: BLE001, S110 — profile is auto-created but never block acceptance
        pass

    emit(
        "terms.accepted",
        user=user,
        actor=user,
        entity_type="terms",
        entity_id=tos_version,
        metadata={"tos_version": tos_version, "privacy_version": privacy_version},
        ip=ip,
    )
    TERMS_ACCEPTANCES_TOTAL.inc()
    return row
