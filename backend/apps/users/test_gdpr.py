"""M11 §7.7 — GDPR personal-data export + 30-day soft delete tests.

The redaction test (``test_export_redacts_broker_and_mfa_secrets``) is AC-gating
(AC-11-8): the export ZIP must contain no broker credentials or MFA secrets.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zipfile

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.m04_testutils import (
    SECRET,
    auth_headers,
    create_broker_account,
    create_strategy,
    create_user,
    create_webhook_config,
)
from apps.users.models import DataExportJob, MFADevice, User

EXPORT_URL = "/api/v1/users/me/export/"
DELETE_URL = "/api/v1/users/me/delete/"
CANCEL_URL = "/api/v1/users/me/delete/cancel/"


def _exports_to_tmp():
    """override_settings kwargs pointing the exports backend at a fresh temp dir."""
    tmp = tempfile.mkdtemp()
    storages = {
        **settings.STORAGES,
        "exports": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp, "base_url": "/media/exports/"},
        },
    }
    return tmp, storages


class _ExportBase(TestCase):
    def setUp(self):
        self.tmp, storages = _exports_to_tmp()
        self._ov = override_settings(STORAGES=storages)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _read_zip(self, job) -> zipfile.ZipFile:
        from apps.users.tasks import export_storage

        with export_storage().open(job.file_key) as fh:
            return zipfile.ZipFile(io.BytesIO(fh.read()))


class GDPRExportTests(_ExportBase):
    def test_export_request_runs_eager_and_produces_ready_zip(self):
        user = create_user(email="exp@example.com")
        resp = self.client.get(EXPORT_URL, **auth_headers(user))
        self.assertEqual(resp.status_code, 202)
        job_id = resp.json()["data"]["job_id"]
        job = DataExportJob.objects.get(id=job_id)
        # CELERY_TASK_ALWAYS_EAGER — the task ran synchronously.
        self.assertEqual(job.status, DataExportJob.Status.READY)
        self.assertTrue(job.file_key)
        self.assertGreater(job.size_bytes, 0)
        names = self._read_zip(job).namelist()
        self.assertIn("account.json", names)
        self.assertIn("orders.json", names)
        self.assertIn("audit_log.json", names)
        self.assertIn("README.txt", names)

    def test_export_redacts_broker_and_mfa_secrets(self):
        """AC-11-8 gate: no broker creds / MFA secrets / webhook secret in the ZIP."""
        user = create_user(email="redact@example.com", mfa=True)
        strat = create_strategy(user)
        wh = create_webhook_config(user, strat, secret=SECRET)
        acct = create_broker_account(user)
        mfa = MFADevice.objects.get(user=user)

        resp = self.client.get(EXPORT_URL, **auth_headers(user))
        job = DataExportJob.objects.get(id=resp.json()["data"]["job_id"])
        from apps.users.tasks import export_storage

        with export_storage().open(job.file_key) as fh:
            raw = fh.read()

        # Plaintext credential material must be absent from the whole archive.
        for plaintext in (b"PKTESTKEYID000000000", b"testsecretvalue000000", SECRET.encode()):
            self.assertNotIn(plaintext, raw, f"plaintext secret leaked: {plaintext!r}")
        # Ciphertext blobs must be absent too (redacted, not just re-encoded).
        for cipher in (acct.api_key_id_enc, acct.api_secret_enc, wh.secret_encrypted, bytes(mfa.secret_encrypted)):
            self.assertNotIn(bytes(cipher), raw, "ciphertext leaked")

        # The broker section explicitly shows [REDACTED] for the key fields.
        zf = zipfile.ZipFile(io.BytesIO(raw))
        brokers = json.loads(zf.read("broker_accounts.json"))
        self.assertEqual(brokers[0]["api_key_id_enc"], "[REDACTED]")
        self.assertEqual(brokers[0]["api_secret_enc"], "[REDACTED]")
        webhooks = json.loads(zf.read("webhook_configs.json"))
        self.assertEqual(webhooks[0]["secret_encrypted"], "[REDACTED]")

    def test_export_includes_user_own_audit_rows(self):
        user = create_user(email="aud@example.com")
        resp = self.client.get(EXPORT_URL, **auth_headers(user))
        job = DataExportJob.objects.get(id=resp.json()["data"]["job_id"])
        rows = json.loads(self._read_zip(job).read("audit_log.json"))
        # At minimum the export_requested event for this user is present.
        self.assertTrue(any(r["event_type"] == "account.export_requested" for r in rows))
        # And every row belongs to this user only (FK serialized under its field name).
        self.assertTrue(all(r["user"] in (str(user.id), None) for r in rows))

    def test_export_status_is_owner_scoped(self):
        alice = create_user(email="alice@example.com")
        bob = create_user(email="bob@example.com")
        resp = self.client.get(EXPORT_URL, **auth_headers(alice))
        job_id = resp.json()["data"]["job_id"]
        # Bob cannot read Alice's job — 404, not 403 (no existence oracle).
        r = self.client.get(f"{EXPORT_URL}{job_id}/", **auth_headers(bob))
        self.assertEqual(r.status_code, 404)
        # Alice can, and gets a signed download URL.
        r2 = self.client.get(f"{EXPORT_URL}{job_id}/", **auth_headers(alice))
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["data"]["status"], "ready")
        self.assertTrue(r2.json()["data"]["download_url"])

    def test_export_reuses_active_job(self):
        user = create_user(email="reuse@example.com")
        # Force a stuck PENDING job so the second request reuses it.
        job = DataExportJob.objects.create(user=user, status=DataExportJob.Status.PENDING)
        resp = self.client.get(EXPORT_URL, **auth_headers(user))
        self.assertEqual(resp.json()["data"]["job_id"], str(job.id))
        self.assertEqual(DataExportJob.objects.filter(user=user).count(), 1)


class GDPRExportDownloadTests(_ExportBase):
    """P1-3 — the filesystem export is served through an authenticated,
    owner-checked, expiry-checked download view (not an unserved /media/ path)."""

    def _ready_job(self, user, *, expires_in_hours=24, content=b"PK\x03\x04zip-bytes"):
        from datetime import timedelta

        from django.core.files.base import ContentFile

        from apps.users.tasks import export_storage

        job = DataExportJob.objects.create(user=user, status=DataExportJob.Status.READY)
        file_key = f"exports/{user.id}/{job.id}.zip"
        export_storage().save(file_key, ContentFile(content))
        job.file_key = file_key
        job.ready_at = timezone.now()
        job.expires_at = timezone.now() + timedelta(hours=expires_in_hours)
        job.save(update_fields=["file_key", "ready_at", "expires_at"])
        return job

    def _url(self, job):
        return f"/api/v1/users/me/export/{job.id}/download/"

    def test_export_download_requires_owner(self):
        owner = create_user()
        job = self._ready_job(owner)
        resp = self.client.get(self._url(job), **auth_headers(owner))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), b"PK\x03\x04zip-bytes")
        self.assertIn("attachment", resp["Content-Disposition"])
        # A different user never even learns the job exists.
        other = create_user(email="other@example.com")
        self.assertEqual(self.client.get(self._url(job), **auth_headers(other)).status_code, 404)

    def test_export_download_404_after_expiry(self):
        owner = create_user()
        job = self._ready_job(owner, expires_in_hours=-1)  # already expired
        self.assertEqual(self.client.get(self._url(job), **auth_headers(owner)).status_code, 410)

    def test_export_url_points_at_served_route_for_filesystem_backend(self):
        from apps.users.tasks import signed_export_url

        owner = create_user()
        job = self._ready_job(owner)
        url = signed_export_url(job)
        self.assertIn(f"/api/v1/users/me/export/{job.id}/download/", url)
        self.assertNotIn("/media/", url)

    def test_expired_exports_evicted(self):
        # P2-6: the nightly task deletes files + rows past expires_at.
        from apps.users.models import DataExportJob
        from apps.users.tasks import evict_expired_exports, export_storage

        owner = create_user()
        expired = self._ready_job(owner, expires_in_hours=-1)
        fresh = self._ready_job(owner, expires_in_hours=24)
        self.assertEqual(evict_expired_exports(), 1)
        self.assertFalse(DataExportJob.objects.filter(id=expired.id).exists())
        self.assertFalse(export_storage().exists(expired.file_key))
        self.assertTrue(DataExportJob.objects.filter(id=fresh.id).exists())  # unexpired kept

    def test_anonymize_purges_exports(self):
        # P2-6: a user's exports (files + rows) don't survive right-to-erasure.
        from apps.users.gdpr import anonymize_user
        from apps.users.models import DataExportJob
        from apps.users.tasks import export_storage

        owner = create_user()
        job = self._ready_job(owner)
        anonymize_user(owner)
        self.assertFalse(DataExportJob.objects.filter(user=owner).exists())
        self.assertFalse(export_storage().exists(job.file_key))


try:
    from moto import mock_aws
    _HAS_MOTO = True
except ImportError:  # pragma: no cover
    _HAS_MOTO = False


@unittest.skipUnless(_HAS_MOTO, "moto not installed")
class GDPRExportS3Tests(TestCase):
    """Prove the S3-compatible backend + 24h presigned URL against a mocked S3."""

    def test_export_to_s3_produces_24h_presigned_url(self):
        import boto3

        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket="stp-exports-test")
            storages = {
                **settings.STORAGES,
                "exports": {
                    "BACKEND": "storages.backends.s3.S3Storage",
                    "OPTIONS": {
                        "bucket_name": "stp-exports-test",
                        "access_key": "testing",
                        "secret_key": "testing",
                        "region_name": "us-east-1",
                        "querystring_auth": True,
                        "querystring_expire": 86400,  # 24h (frozen decision §4.2)
                        "default_acl": None,
                        "file_overwrite": True,
                    },
                },
            }
            with override_settings(STORAGES=storages):
                user = create_user(email="s3@example.com")
                resp = self.client.get(EXPORT_URL, **auth_headers(user))
                job = DataExportJob.objects.get(id=resp.json()["data"]["job_id"])
                self.assertEqual(job.status, DataExportJob.Status.READY)
                # Object really landed in the (mocked) bucket.
                obj = s3.get_object(Bucket="stp-exports-test", Key=job.file_key)
                self.assertGreater(obj["ContentLength"], 0)
                # Status endpoint returns a presigned URL with a 24h expiry.
                r = self.client.get(f"{EXPORT_URL}{job.id}/", **auth_headers(user))
                url = r.json()["data"]["download_url"]
                # Robust to both signature styles: SigV4 (X-Amz-Signature +
                # X-Amz-Expires=86400) and SigV2 (Signature= + Expires=<epoch>).
                self.assertIn("Signature", url)
                if "X-Amz-Expires" in url:
                    self.assertIn("X-Amz-Expires=86400", url)
                else:
                    import re
                    import time

                    m = re.search(r"[?&]Expires=(\d+)", url)
                    self.assertIsNotNone(m, f"no Expires in presigned URL: {url}")
                    ttl = int(m.group(1)) - int(time.time())
                    self.assertGreater(ttl, 86400 - 600)  # ~24h ahead
                    self.assertLessEqual(ttl, 86400 + 5)


class AccountDeleteTests(_ExportBase):
    def test_delete_sets_pending_and_emails(self):
        user = create_user(email="del@example.com")
        resp = self.client.post(DELETE_URL, **auth_headers(user))
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertIsNotNone(user.pending_delete_at)
        delta = user.pending_delete_at - timezone.now()
        self.assertGreater(delta.days, 28)
        self.assertLessEqual(delta.days, 30)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            AuditLog.objects.filter(user_id=user.id, event_type="account.delete_requested").exists()
        )

    def test_delete_cancel_clears_pending(self):
        user = create_user(email="cancel@example.com")
        self.client.post(DELETE_URL, **auth_headers(user))
        resp = self.client.post(CANCEL_URL, **auth_headers(user))
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertIsNone(user.pending_delete_at)

    def test_cancel_without_pending_is_409(self):
        user = create_user(email="nopending@example.com")
        resp = self.client.post(CANCEL_URL, **auth_headers(user))
        self.assertEqual(resp.status_code, 409)

    def test_anonymize_expired_keeps_pk_and_scrubs_pii(self):
        from decimal import Decimal

        from apps.orders.models import Fill, Order, Position

        user = create_user(email="expire@example.com", mfa=True)
        acct = create_broker_account(user)
        # Exercise a user WITH trading history so broker-account deletion hits the
        # real FK graph (Order SET_NULL, Fill/Position CASCADE) — not an empty
        # account. A silently-swallowed delete failure here would leave the
        # encrypted keys in the DB while reporting "anonymized".
        strat = create_strategy(user, slug="expire-strat")
        order = Order.objects.create(
            user=user, strategy=strat, broker_account=acct,
            client_order_id="ex-c1", broker_order_id="ex-b1", symbol="AAPL",
            side=Order.Side.BUY, qty=Decimal("2"), status=Order.Status.FILLED,
        )
        Fill.objects.create(
            order=order, broker_account=acct, qty=Decimal("2"), price=Decimal("100"),
            ts=timezone.now(), broker_exec_id="ex-x1",
        )
        Position.objects.create(
            user=user, broker_account=acct, symbol="AAPL", qty=Decimal("2"), avg_cost=Decimal("100"),
        )
        uid = user.id
        # Emit an audit row so we can prove the FK still resolves after anonymize.
        from apps.audit.services import emit

        emit("account.delete_requested", user=user, actor=user)
        user.pending_delete_at = timezone.now() - timezone.timedelta(minutes=1)
        user.save(update_fields=["pending_delete_at"])

        from apps.users.tasks import anonymize_expired_accounts

        count = anonymize_expired_accounts()
        self.assertEqual(count, 1)

        # Row survives under its PK; PII scrubbed; secrets dropped.
        row = User.objects.get(pk=uid)
        self.assertNotEqual(row.email, "expire@example.com")
        self.assertTrue(row.email.endswith("@anonymized.invalid"))
        self.assertFalse(row.is_active)
        self.assertIsNone(row.pending_delete_at)
        self.assertFalse(MFADevice.objects.filter(user=row).exists())
        from apps.brokers.models import BrokerAccount

        self.assertFalse(BrokerAccount.objects.filter(user=row).exists())
        # Audit FK still resolves + an anonymized event was recorded.
        self.assertTrue(AuditLog.objects.filter(user_id=uid).exists())
        self.assertTrue(AuditLog.objects.filter(user_id=uid, event_type="account.anonymized").exists())

    def test_anonymize_skips_non_expired(self):
        user = create_user(email="future@example.com")
        user.pending_delete_at = timezone.now() + timezone.timedelta(days=30)
        user.save(update_fields=["pending_delete_at"])
        from apps.users.tasks import anonymize_expired_accounts

        self.assertEqual(anonymize_expired_accounts(), 0)
        user.refresh_from_db()
        self.assertEqual(user.email, "future@example.com")
