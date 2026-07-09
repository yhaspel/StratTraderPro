"""Data-migration proof (AC-10-1 / §8): seed AuthEvent fixtures at the pre-drop
state, migrate to head, assert row-count parity + the rebuilt chain verifies.

Runs on the default SQLite lane (0003 is reversible there, so the executor can
stage the 'before' state). The migration's own ``forwards`` also asserts parity +
head-hash internally, so a clean forward apply is itself part of the proof.
"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from apps.audit.models import AuditLog
from apps.audit.verifier import verify_chain

_BEFORE = [("audit", "0002_chain_triggers"), ("users", "0003_oauth_exchange_code")]
_AFTER = [("audit", "0003_migrate_auth_events"), ("users", "0004_drop_auth_event")]


class AuthEventDataMigrationTests(TransactionTestCase):
    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor

    def tearDown(self):
        # Leave the DB at head for the rest of the suite.
        self._migrate(_AFTER)

    def test_auth_events_become_a_verified_chain(self):
        executor = self._migrate(_BEFORE)
        old_apps = executor.loader.project_state(_BEFORE).apps
        AuthEvent = old_apps.get_model("users", "AuthEvent")

        fixtures = [
            ("login_ok", "one@x.com", "1.2.3.4", {"family_id": "f1"}),
            ("mfa_challenge_ok", "two@x.com", None, {}),
            ("login_fail", "three@x.com", "5.6.7.8", {"reason": "bad_pw"}),
        ]
        for event_type, email, ip, meta in fixtures:
            AuthEvent.objects.create(
                user=None, email=email, event_type=event_type, ip=ip,
                user_agent="fixture-agent", metadata=meta,
            )
        source_count = AuthEvent.objects.count()

        # Migrate forward — the migration self-asserts parity + head hash.
        self._migrate(_AFTER)

        self.assertEqual(AuditLog.objects.count(), source_count)
        self.assertEqual(
            set(AuditLog.objects.values_list("event_type", flat=True)),
            {"auth.login_ok", "auth.mfa_challenge_ok", "auth.login_fail"},
        )
        # The rebuilt chain verifies end-to-end.
        self.assertTrue(verify_chain()["ok"])
        # Secrets/emails fold into data_after; ordering preserved by (occurred_at, id).
        first = AuditLog.objects.order_by("id").first()
        self.assertEqual(first.data_after["email"], "one@x.com")
