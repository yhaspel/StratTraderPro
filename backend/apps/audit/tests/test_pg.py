"""Postgres-lane tests (M10 §10.2, AC-10-3/§10.5/§10.2 index proxy).

Run with ``-m pg`` against a real Postgres (``config.settings.test_pg``). Every
test also carries ``@skipUnless(connection.vendor == "postgresql")`` so the same
file is a clean skip on the default SQLite lane.
"""
import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext  # noqa: F401  (kept for future EXPLAIN tooling)

from apps.audit.hashing import GENESIS_PREV_HASH
from apps.audit.models import AuditLog
from apps.audit.services import emit
from apps.audit.verifier import triggers_present, verify_chain

pytestmark = pytest.mark.pg

_PG = connection.vendor == "postgresql"
User = get_user_model()


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL")
class TriggerEnforcementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pg@x.com", password="pw-123456789A")
        self.row = emit("admin.user_disabled", user=self.user, data_after={"i": 0})

    def test_update_blocked_for_owner(self):
        with self.assertRaises(Exception) as ctx, transaction.atomic():
            AuditLog.objects.filter(id=self.row.id).update(ua="tampered")
        self.assertIn("append-only", str(ctx.exception).lower())

    def test_delete_blocked_for_owner(self):
        with self.assertRaises(Exception) as ctx, transaction.atomic():
            AuditLog.objects.filter(id=self.row.id).delete()
        self.assertIn("append-only", str(ctx.exception).lower())

    def test_stale_prev_hash_rejected(self):
        with self.assertRaises(Exception) as ctx, transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (occurred_at, event_type, entity_type, entity_id, "
                "ua, prev_hash, self_hash) VALUES (now(), 'x', '', '', '', %s, %s)",
                ["a" * 64, "b" * 64],
            )
        self.assertIn("linkage", str(ctx.exception).lower())

    def test_malformed_self_hash_rejected(self):
        with self.assertRaises(Exception) as ctx, transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (occurred_at, event_type, entity_type, entity_id, "
                "ua, prev_hash, self_hash) VALUES (now(), 'x', '', '', '', %s, %s)",
                [self.row.self_hash, "NOT-HEX"],
            )
        self.assertIn("malformed", str(ctx.exception).lower())

    def test_triggers_present(self):
        self.assertTrue(triggers_present())

    def test_restricted_role_cannot_mutate(self):
        # role name is a hardcoded constant — no injection surface (S608 noqa'd).
        role = "audit_restricted_test"
        with connection.cursor() as cur:
            cur.execute(  # noqa: S608
                f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{role}') "
                f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$;"
            )
            cur.execute(f"GRANT SELECT, INSERT ON audit_log TO {role}")  # noqa: S608
            # As the restricted role, UPDATE is a privilege error (before triggers).
            cur.execute(f"SET ROLE {role}")  # noqa: S608
            with self.assertRaises(Exception) as ctx:
                cur.execute(f"UPDATE audit_log SET ua='x' WHERE id={self.row.id}")  # noqa: S608
            self.assertIn("permission denied", str(ctx.exception).lower())


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL")
class IndexUsageTests(TransactionTestCase):
    """AC-10-6 CI proxy: the filtered audit search must use an index, not seq-scan."""

    reset_sequences = True

    def test_event_type_occurred_at_index_used(self):
        user = User.objects.create_user(email="idx@x.com", password="pw-123456789A")
        # Seed enough rows that the planner would seq-scan without an index.
        for i in range(2000):
            emit("admin.user_disabled" if i % 2 else "order.submitted", user=user, data_after={"i": i})
        with connection.cursor() as cur:
            cur.execute("ANALYZE audit_log")
            cur.execute(
                "EXPLAIN SELECT * FROM audit_log WHERE event_type='order.submitted' "
                "ORDER BY occurred_at DESC LIMIT 25"
            )
            plan = "\n".join(r[0] for r in cur.fetchall())
        self.assertIn("Index", plan, msg=f"expected an index scan, got:\n{plan}")


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL")
class ConcurrencyTests(TransactionTestCase):
    """Advisory-lock proof: parallel emits still form one valid chain."""

    def test_concurrent_emits_form_valid_chain(self):
        user = User.objects.create_user(email="conc@x.com", password="pw-123456789A")
        n_threads, per = 4, 10

        def worker():
            for _ in range(per):
                emit("order.fill_ingested", user=user, data_after={"t": threading.get_ident()})
            connection.close()

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(AuditLog.objects.count(), n_threads * per)
        self.assertTrue(verify_chain()["ok"])
        # First row is genesis, exactly one.
        self.assertEqual(AuditLog.objects.filter(prev_hash=GENESIS_PREV_HASH).count(), 1)
