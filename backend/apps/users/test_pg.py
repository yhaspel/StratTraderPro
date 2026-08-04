"""Postgres-only concurrency tests for the users app (run with ``-m pg``)."""
from __future__ import annotations

import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.users.models import RefreshTokenFamily
from apps.users.services import issue_token_pair, rotate_refresh

pytestmark = pytest.mark.pg

_PG = connection.vendor == "postgresql"
User = get_user_model()


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL")
class ConcurrentRefreshTests(TransactionTestCase):
    """P2-8: two simultaneous refreshes of the same token must not self-revoke
    the family — the row lock serializes them and the one-step grace tolerates
    the double-submit."""

    def test_concurrent_refresh_does_not_revoke_family(self):
        user = User.objects.create_user(email="conc-refresh@x.com", password="pw-123456789A")
        raw = issue_token_pair(user)["refresh"]
        results: list[object] = []

        def worker():
            try:
                results.append(rotate_refresh(raw))
            except InvalidToken as exc:  # pragma: no cover — should not happen post-fix
                results.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        family = RefreshTokenFamily.objects.get(user=user)
        self.assertFalse(family.is_revoked, "concurrent refresh must not revoke the family")
        # Both refreshes succeeded (grace on the loser), neither raised.
        self.assertTrue(all(isinstance(r, dict) for r in results), results)
