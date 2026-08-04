"""Shared admin-portal test helpers."""
from __future__ import annotations

import pyotp
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

from apps.users.mfa import encrypt_secret, generate_totp_secret
from apps.users.models import MFADevice

User = get_user_model()


def make_user(email, *, is_staff=False, mfa=False, is_active=True):
    u = User.objects.create_user(email=email, password="pw-123456789A", is_active=is_active)  # noqa: S106
    if is_staff:
        u.is_staff = True
        u.save(update_fields=["is_staff"])
    secret = None
    if mfa:
        secret = generate_totp_secret()
        MFADevice.objects.create(user=u, secret_encrypted=encrypt_secret(secret), verified=True)
    return u, secret


def totp(secret) -> str:
    return pyotp.TOTP(secret, interval=30, digits=6).now()


def bearer(user) -> str:
    return f"Bearer {AccessToken.for_user(user)}"


def auth_client(user):
    from rest_framework.test import APIClient

    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=bearer(user))
    return c
