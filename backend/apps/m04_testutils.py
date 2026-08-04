"""Shared test helpers for M04 (webhooks / brokers / orders / dashboard).

Not a test module (no ``test_`` prefix) so pytest does not collect it.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.brokers.base import BrokerContext
from apps.brokers.fake import FakeBrokerAdapter
from apps.brokers.models import BrokerAccount
from apps.brokers.services import encrypt_key
from apps.strategies.models import Strategy, WebhookConfig
from apps.strategies.services import default_json_schema
from apps.strategies.services import encrypt_secret as wh_encrypt_secret
from apps.users.mfa import encrypt_secret, generate_totp_secret
from apps.users.models import MFADevice
from apps.users.services import issue_token_pair

User = get_user_model()
PW = "SecurePass123!"
SECRET = "test-webhook-secret-abc123XYZ"  # noqa: S105 — test fixture, not a real credential


def create_user(email="trader@example.com", *, mfa=True, staff=False):
    u = User.objects.create_user(email=email, password=PW, display_name="Trader")
    u.is_verified = True
    if staff:
        u.is_staff = True
    u.save()
    if mfa:
        MFADevice.objects.create(
            user=u, secret_encrypted=encrypt_secret(generate_totp_secret()), verified=True
        )
    return u


def auth_headers(user) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def access_token(user) -> str:
    return issue_token_pair(user)["access"]


def create_strategy(user, slug="demo", name="Demo"):
    return Strategy.objects.create(owner=user, name=name, slug=slug, is_system=False)


def create_webhook_config(user, strategy, secret=SECRET, schema=None):
    return WebhookConfig.objects.create(
        user=user,
        strategy=strategy,
        secret_encrypted=wh_encrypt_secret(secret),
        json_schema=schema if schema is not None else default_json_schema(),
        payload_template={},
        version=1,
    )


def create_broker_account(user, *, is_default=True, account_number="PATEST001", status=None):
    return BrokerAccount.objects.create(
        user=user,
        broker=BrokerAccount.Broker.ALPACA,
        mode=BrokerAccount.Mode.PAPER,
        api_key_id_enc=encrypt_key("PKTESTKEYID000000000"),
        api_secret_enc=encrypt_key("testsecretvalue000000"),
        account_number=account_number,
        is_default=is_default,
        status=status or BrokerAccount.Status.CONNECTED,
    )


def valid_alert(secret=SECRET, **overrides):
    body = {
        "strategy": "demo",
        "action": "buy",
        "symbol": "AAPL",
        "qty": 1,
        "order_type": "MKT",
        "sig": secret,
        "idempotency_key": "tv-alert-1",
    }
    body.update(overrides)
    return body


def fake_factory(script=None, **kw):
    """Return a callable suitable for patching ``build_adapter`` — builds a
    FakeBrokerAdapter bound to the account's real user_id."""

    def _factory(account):
        return FakeBrokerAdapter(
            BrokerContext(account_id=str(account.id), user_id=str(account.user_id)),
            script=script,
            **kw,
        )

    return _factory


__all__ = [
    "Decimal",
    "User",
    "PW",
    "SECRET",
    "create_user",
    "auth_headers",
    "access_token",
    "create_strategy",
    "create_webhook_config",
    "create_broker_account",
    "valid_alert",
    "fake_factory",
]
