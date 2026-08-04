"""Golden-vector + canonicalization tests for the hash chain (AC-10-1, ADR-100).

The pinned digests below are the guard against silent canonicalization drift:
any refactor that changes the canonical bytes or the SHA-256 chaining will fail
these exact-match assertions (§16).
"""
from datetime import datetime, timezone

from django.test import SimpleTestCase

from apps.audit.hashing import (
    GENESIS_PREV_HASH,
    canonical_payload,
    compute_self_hash,
    iso_timestamp,
    normalize_json,
)

_DT1 = datetime(2026, 7, 9, 12, 34, 56, 123456, tzinfo=timezone.utc)
_DT2 = datetime(2026, 7, 9, 12, 35, 0, 0, tzinfo=timezone.utc)


class GoldenVectorTests(SimpleTestCase):
    def test_genesis_prev_hash_is_64_zeros(self):
        self.assertEqual(GENESIS_PREV_HASH, "0" * 64)

    def test_row1_canonical_payload_exact_bytes(self):
        payload = canonical_payload(
            occurred_at=_DT1,
            user_id="11111111-1111-1111-1111-111111111111",
            actor_id=None,
            event_type="auth.login_ok",
            data_after={"email": "a@b.com"},
            ip="1.2.3.4",
            ua="pytest",
        )
        self.assertEqual(
            payload,
            (
                '{"actor_id":null,"data_after":{"email":"a@b.com"},"data_before":null,'
                '"entity_id":"","entity_type":"","event_type":"auth.login_ok","ip":"1.2.3.4",'
                '"occurred_at":"2026-07-09T12:34:56.123456+00:00","ua":"pytest",'
                '"user_id":"11111111-1111-1111-1111-111111111111"}'
            ).encode("utf-8"),
        )

    def test_row1_self_hash_golden(self):
        payload = canonical_payload(
            occurred_at=_DT1,
            user_id="11111111-1111-1111-1111-111111111111",
            actor_id=None,
            event_type="auth.login_ok",
            data_after={"email": "a@b.com"},
            ip="1.2.3.4",
            ua="pytest",
        )
        self.assertEqual(
            compute_self_hash(GENESIS_PREV_HASH, payload),
            "7121cf4bb542671efff853ced5233cb1fa09567cc6750235f33122d2e10628b3",
        )

    def test_row2_chains_on_row1_golden(self):
        h1 = "7121cf4bb542671efff853ced5233cb1fa09567cc6750235f33122d2e10628b3"
        payload = canonical_payload(
            occurred_at=_DT2,
            user_id=None,
            actor_id="22222222-2222-2222-2222-222222222222",
            event_type="admin.user_disabled",
            entity_type="user",
            entity_id="u-9",
            data_before={"is_active": True},
            data_after={"is_active": False},
        )
        self.assertEqual(
            compute_self_hash(h1, payload),
            "fd244e1edfd518d4da144b854ab3ebdb754ed48981cef27ffdbbde9f6407d6d5",
        )

    def test_whole_second_timestamp_keeps_microseconds(self):
        # A .000000 timestamp must still serialize with microseconds so a row
        # hashed on write verifies on read.
        self.assertEqual(iso_timestamp(_DT2), "2026-07-09T12:35:00.000000+00:00")

    def test_key_order_independent(self):
        # Sorted keys → insertion order of data_after must not change the digest.
        a = canonical_payload(occurred_at=_DT1, user_id=None, actor_id=None,
                              event_type="x", data_after={"a": 1, "b": 2})
        b = canonical_payload(occurred_at=_DT1, user_id=None, actor_id=None,
                              event_type="x", data_after={"b": 2, "a": 1})
        self.assertEqual(a, b)

    def test_normalize_json_coerces_decimal(self):
        from decimal import Decimal

        self.assertEqual(normalize_json({"px": Decimal("1.50")}), {"px": "1.50"})
