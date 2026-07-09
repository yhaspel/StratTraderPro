"""Verifier tests (AC-10-2): tamper detection, linkage break, cursor resume.

On SQLite the enforcement triggers do not exist, so a direct ORM ``update()``
CAN mutate a row — which is exactly why the Python verifier must catch it.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit.models import AuditLog, AuditVerifierState
from apps.audit.services import emit
from apps.audit.verifier import run_verifier, verify_chain

User = get_user_model()


class VerifierTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="v@x.com", password="pw-123456789A")
        for i in range(5):
            emit("admin.user_disabled", user=self.user, data_after={"i": i})

    def test_clean_chain_verifies(self):
        result = verify_chain()
        self.assertTrue(result["ok"])
        self.assertEqual(result["checked"], 5)

    def test_detects_row_tamper(self):
        target = AuditLog.objects.order_by("id")[2]
        AuditLog.objects.filter(id=target.id).update(data_after={"i": 999})
        result = verify_chain()
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_id"], target.id)
        self.assertEqual(result["reason"], "hash_mismatch")

    def test_detects_linkage_break(self):
        target = AuditLog.objects.order_by("id")[3]
        AuditLog.objects.filter(id=target.id).update(prev_hash="f" * 64)
        result = verify_chain()
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_id"], target.id)
        self.assertEqual(result["reason"], "linkage_break")

    def test_cursor_resume_only_checks_new_rows(self):
        setup_max = AuditLog.objects.order_by("-id").first().id  # the 5 setup rows
        # First run verifies all 5 and advances the cursor to setup_max. The
        # completion row (setup_max+1) is written AFTER the cursor save, so it is
        # left for the next run to verify.
        run_verifier()
        state = AuditVerifierState.load()
        self.assertEqual(state.result, "ok")
        self.assertEqual(state.last_verified_id, setup_max)
        # Add two more; a resumed verify_chain from the cursor checks the pending
        # completion row + the two new rows (3), not the already-verified 5.
        emit("admin.user_enabled", user=self.user)
        emit("admin.user_enabled", user=self.user)
        result = verify_chain(start_id=state.last_verified_id, start_prev_hash=state.last_verified_hash)
        self.assertTrue(result["ok"])
        self.assertEqual(result["checked"], 3)

    def test_run_verifier_writes_completion_row_on_success(self):
        before = AuditLog.objects.count()
        run_verifier()
        self.assertTrue(
            AuditLog.objects.filter(event_type="audit.verifier_completed").exists()
        )
        self.assertGreater(AuditLog.objects.count(), before)

    def test_run_verifier_records_failure_row_on_tamper(self):
        target = AuditLog.objects.order_by("id")[1]
        AuditLog.objects.filter(id=target.id).update(data_after={"tampered": True})
        out = run_verifier()
        self.assertFalse(out["ok"])
        self.assertTrue(AuditLog.objects.filter(event_type="audit.integrity_failure").exists())
        # Cursor did NOT advance past the tamper on failure.
        state = AuditVerifierState.load()
        self.assertEqual(state.result, "fail")
