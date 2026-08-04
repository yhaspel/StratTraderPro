"""M03 — strategy-level permission helpers.

The MFA gate is provided by ``apps.users.permissions.IsAuthenticatedAndMFAEnforced``
and applied at the view level. These extra checks live in the views as
explicit guards rather than in DRF object-level permissions because the
"system" rules (AC-03-10) cut across multiple actions.
"""
from __future__ import annotations

from .models import Strategy


def can_user_view(user, strategy: Strategy) -> bool:
    """Anyone authenticated can view system strategies. Users see their own
    too (across enabled + disabled — disabled is filtered at list level only).
    """
    if strategy.is_system:
        return True
    return strategy.owner_id == user.id


def can_user_modify(user, strategy: Strategy) -> bool:
    """User can modify only their own strategies. System strategies require
    staff via Django admin (AC-03-10)."""
    if strategy.is_system:
        return user.is_staff
    return strategy.owner_id == user.id


def can_user_delete(user, strategy: Strategy) -> bool:
    """User soft-deletes their own; system strategies cannot be deleted via
    API (AC-03-10)."""
    if strategy.is_system:
        return False
    return strategy.owner_id == user.id
