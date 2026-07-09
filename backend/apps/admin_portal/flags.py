"""Feature-flag read/flip helper (M10 §6.4, ADR-101).

Resolution order for a mutable flag: 30 s process-local cache → Redis
(``flag:{name}``, 60 s TTL, via the Django cache) → DB ``FeatureFlag`` row →
registry default (the env-parsed settings value). Immutable flags short-circuit
to ``settings.<NAME>`` so their env-only nature is unmissable. Everything
fails OPEN to the env default — flag plumbing must never take the platform down,
and it must be safe before the ``FeatureFlag`` table exists (during ``migrate``).
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.db.utils import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)

LOCAL_CACHE_TTL = 30  # seconds
REDIS_TTL = 60  # seconds

# Patched by tests to time-travel the local cache without sleeping.
_monotonic = time.monotonic

# name -> (value, monotonic_expiry)
_local_cache: dict[str, tuple[bool, float]] = {}


class FlagImmutable(Exception):
    """Raised when a flip targets an env-only (immutable) flag."""


def _registry() -> dict:
    return getattr(settings, "FEATURE_FLAGS_REGISTRY", {})


def _redis_key(name: str) -> str:
    return f"flag:{name}"


def _env_default(name: str) -> bool:
    reg = _registry().get(name)
    if reg is not None:
        return bool(reg["default"])
    return bool(getattr(settings, name, False))


def _cache_local(name: str, value: bool) -> None:
    _local_cache[name] = (value, _monotonic() + LOCAL_CACHE_TTL)


def _bust_local(name: str | None = None) -> None:
    if name is None:
        _local_cache.clear()
    else:
        _local_cache.pop(name, None)


def is_enabled(name: str) -> bool:
    """Effective value of ``name`` (call-time only; never at import)."""
    reg = _registry().get(name)
    # Immutable flags are env-only forever.
    if reg is not None and not reg["mutable"]:
        return bool(getattr(settings, name, reg["default"]))

    # 1) process-local cache
    hit = _local_cache.get(name)
    if hit is not None and hit[1] > _monotonic():
        return hit[0]

    default = _env_default(name)

    # 2) Redis (via Django cache)
    try:
        cached = cache.get(_redis_key(name))
        if cached is not None:
            value = bool(cached)
            _cache_local(name, value)
            return value
    except Exception:  # noqa: BLE001 — fail open
        logger.warning("flags.redis_read_failed", extra={"flag": name})
        _cache_local(name, default)
        return default

    # 3) DB row (source of truth) — safe before the table exists
    try:
        from .models import FeatureFlag

        row = FeatureFlag.objects.filter(name=name).values_list("enabled", flat=True).first()
    except (ProgrammingError, OperationalError):
        return default
    except Exception:  # noqa: BLE001 — fail open
        logger.warning("flags.db_read_failed", extra={"flag": name})
        return default

    value = default if row is None else bool(row)
    # Populate Redis so other processes converge without hitting the DB.
    try:
        cache.set(_redis_key(name), value, REDIS_TTL)
    except Exception:  # noqa: BLE001,S110 — Redis write is best-effort
        pass
    _cache_local(name, value)
    return value


def source(name: str) -> str:
    """Where the current value comes from: ``db`` or ``env-default``."""
    reg = _registry().get(name)
    if reg is not None and not reg["mutable"]:
        return "env-default"
    try:
        from .models import FeatureFlag

        return "db" if FeatureFlag.objects.filter(name=name).exists() else "env-default"
    except (ProgrammingError, OperationalError):
        return "env-default"


def set_flag(name: str, enabled: bool, *, actor=None, request=None, note: str = "") -> bool:
    """Flip a mutable flag: DB write → Redis set → local bust → audit + metric.

    Raises ``FlagImmutable`` for env-only flags, ``KeyError`` for unknown flags.
    """
    reg = _registry().get(name)
    if reg is None:
        raise KeyError(name)
    if not reg["mutable"]:
        raise FlagImmutable(name)

    from .metrics import FEATURE_FLAG_FLIPS
    from .models import FeatureFlag

    before = is_enabled(name)
    FeatureFlag.objects.update_or_create(
        name=name,
        defaults={"enabled": bool(enabled), "updated_by": actor, "note": note[:255]},
    )
    try:
        cache.set(_redis_key(name), bool(enabled), REDIS_TTL)
    except Exception:  # noqa: BLE001,S110 — Redis write is best-effort
        pass
    _bust_local(name)

    from apps.audit.events import AuditEventType
    from apps.audit.services import emit

    emit(
        AuditEventType.FLAG_FLIPPED,
        actor=actor,
        request=request,
        entity_type="feature_flag",
        entity_id=name,
        data_before={"enabled": before},
        data_after={"enabled": bool(enabled), "note": note},
    )
    FEATURE_FLAG_FLIPS.labels(flag=name).inc()
    return bool(enabled)


def flag_state(name: str) -> dict:
    reg = _registry().get(name, {})
    return {
        "name": name,
        "enabled": is_enabled(name),
        "source": source(name),
        "mutable": reg.get("mutable", False),
        "dangerous": reg.get("dangerous", False),
        "description": reg.get("description", ""),
        "default": bool(reg.get("default", False)),
    }


def all_flags() -> list[dict]:
    return [flag_state(name) for name in _registry()]
