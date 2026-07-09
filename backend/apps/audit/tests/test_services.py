"""emit() write-path tests (AC-10-1): chaining, scrubbing, capture, never-raises."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.audit.hashing import GENESIS_PREV_HASH, canonical_payload, compute_self_hash
from apps.audit.models import AuditLog
from apps.audit.services import emit

User = get_user_model()


class EmitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="e@x.com", password="pw-123456789A")
        self.actor = User.objects.create_user(email="a@x.com", password="pw-123456789A", is_staff=True)

    def test_first_row_is_genesis_chained(self):
        row = emit("admin.user_disabled", user=self.user, actor=self.actor,
                   entity_type="user", entity_id=str(self.user.id))
        self.assertIsNotNone(row)
        self.assertEqual(row.prev_hash, GENESIS_PREV_HASH)
        self.assertRegex(row.self_hash, r"^[0-9a-f]{64}$")

    def test_second_row_chains_on_first(self):
        r1 = emit("admin.user_disabled", user=self.user, actor=self.actor)
        r2 = emit("admin.user_enabled", user=self.user, actor=self.actor)
        self.assertEqual(r2.prev_hash, r1.self_hash)

    def test_stored_row_reverifies(self):
        # Property: what we hashed on write == what we can recompute from the row.
        row = emit("risk.profile_changed", user=self.user,
                   data_before={"a": 1}, data_after={"a": 2})
        payload = canonical_payload(
            occurred_at=row.occurred_at, user_id=row.user_id, actor_id=row.actor_id,
            event_type=row.event_type, entity_type=row.entity_type, entity_id=row.entity_id,
            data_before=row.data_before, data_after=row.data_after, ip=row.ip, ua=row.ua,
        )
        self.assertEqual(compute_self_hash(row.prev_hash, payload), row.self_hash)

    def test_secrets_are_scrubbed(self):
        row = emit(
            "strategy.secret_rotated",
            user=self.user,
            data_after={"secret": "supersecret", "mfa_code": "123456", "version": 3},
        )
        self.assertEqual(row.data_after["secret"], "***REDACTED***")
        self.assertEqual(row.data_after["mfa_code"], "***REDACTED***")
        self.assertEqual(row.data_after["version"], 3)
        # And the secret never appears anywhere in the persisted payload.
        self.assertNotIn("supersecret", str(row.data_after))

    def test_captures_ip_and_ua_from_request(self):
        req = RequestFactory().post("/x", HTTP_USER_AGENT="UnitAgent/1.0",
                                    HTTP_X_FORWARDED_FOR="9.9.9.9, 10.0.0.1")
        row = emit("broker.connect", user=self.user, request=req)
        self.assertEqual(row.ip, "9.9.9.9")
        self.assertEqual(row.ua, "UnitAgent/1.0")

    def test_metadata_folds_into_data_after(self):
        row = emit("flag.flipped", actor=self.actor, metadata={"flag": "BACKTEST_ENABLED", "enabled": False})
        self.assertEqual(row.data_after["flag"], "BACKTEST_ENABLED")
        self.assertIs(row.data_after["enabled"], False)

    def test_never_raises_and_drops_on_failure(self):
        with patch("apps.audit.models.AuditLog.objects") as mgr:
            mgr.order_by.side_effect = RuntimeError("db exploded")
            # Must not raise; returns None.
            self.assertIsNone(emit("order.submitted", user=self.user))

    def test_record_event_repoint_writes_auth_namespace(self):
        from apps.users.services import record_event

        record_event("login_ok", user=self.user)
        self.assertTrue(AuditLog.objects.filter(event_type="auth.login_ok", user=self.user).exists())
