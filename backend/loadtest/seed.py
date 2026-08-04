#!/usr/bin/env python
"""M11 §7.4 — seed load-test fixtures and write ``fixtures.json`` for locust.

Creates N namespaced users, each with:
  - a verified account + a verified ``MFADevice`` (known TOTP secret, so the L1
    kill-switch MFA step-up can be answered), MFA-enrolled so ``/ws/dashboard/``
    accepts the token,
  - a ``Strategy`` + a ``WebhookConfig`` with a KNOWN static ``sig`` secret,
  - (optional) a CONNECTED Alpaca paper ``BrokerAccount`` so webhook-driven
    orders have a broker to route to. On a DEDICATED load stack the
    FakeBrokerAdapter seam (see fake_broker_patch.py) turns these into
    deterministic in-memory fills; do NOT enable that seam on the shared stack.

Run it INSIDE the backend container so encryption keys (FERNET_KEK derives from
SECRET_KEY) and the DB host match the running stack exactly:

    docker exec strattraderpro-backend-1 python /app/loadtest/seed.py --count 100 --with-broker

Everything it writes is namespaced (default prefix ``loadtest+``) and reversible:

    docker exec strattraderpro-backend-1 python /app/loadtest/seed.py --purge

NOTE: ``--purge`` will fail for any user already referenced by an append-only
``audit_log`` row (a successful ORDER_SUBMITTED). Seed + a `--no-broker` smoke
produce no audit rows and purge cleanly; a full fills run does not.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

# --- Django bootstrap (works standalone or via `python loadtest/seed.py`) ----
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

import pyotp  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402

from apps.brokers.models import BrokerAccount  # noqa: E402
from apps.brokers.services import encrypt_key  # noqa: E402
from apps.strategies.models import Strategy, WebhookConfig  # noqa: E402
from apps.strategies.services import default_json_schema  # noqa: E402
from apps.strategies.services import encrypt_secret as wh_encrypt_secret  # noqa: E402
from apps.users.mfa import encrypt_secret as mfa_encrypt_secret  # noqa: E402
from apps.users.models import MFADevice  # noqa: E402
from apps.users.services import issue_token_pair  # noqa: E402

User = get_user_model()

PASSWORD = "LoadTest123!secure"


def _email(prefix: str, i: int) -> str:
    return f"{prefix}{i:03d}@stp.local"


def purge(prefix: str) -> None:
    qs = User.objects.filter(email__startswith=prefix)
    n = qs.count()
    ok, failed = 0, 0
    for u in qs:
        try:
            with transaction.atomic():
                u.delete()
            ok += 1
        except Exception as exc:  # noqa: BLE001 — likely an append-only audit FK
            failed += 1
            print(f"  ! could not delete {u.email}: {exc}", file=sys.stderr)
    print(f"purge: matched={n} deleted={ok} kept(referenced)={failed}")


def seed(*, count: int, prefix: str, with_broker: bool) -> list[dict]:
    users: list[dict] = []
    for i in range(count):
        email = _email(prefix, i)
        totp_secret = pyotp.random_base32(length=32)
        webhook_secret = f"lt-sig-{i:03d}-{secrets.token_hex(12)}"

        with transaction.atomic():
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"display_name": f"LoadTest {i:03d}"},
            )
            if created:
                user.set_password(PASSWORD)
            user.is_verified = True
            user.is_active = True
            user.save()

            # Verified MFA device (single source of truth for user.mfa_enabled).
            dev, _ = MFADevice.objects.get_or_create(user=user)
            dev.secret_encrypted = mfa_encrypt_secret(totp_secret)
            dev.verified = True
            dev.save()

            strat, _ = Strategy.objects.get_or_create(
                owner=user, slug=f"lt-{i:03d}",
                defaults={"name": f"LoadTest Strategy {i:03d}", "is_system": False},
            )

            wc, _ = WebhookConfig.objects.get_or_create(
                user=user, strategy=strat,
                defaults={
                    "secret_encrypted": wh_encrypt_secret(webhook_secret),
                    "json_schema": default_json_schema(),
                    "payload_template": {},
                    "version": 1,
                },
            )
            # Rotate the secret to the known value on re-seed.
            wc.secret_encrypted = wh_encrypt_secret(webhook_secret)
            wc.save(update_fields=["secret_encrypted"])

            if with_broker:
                BrokerAccount.objects.get_or_create(
                    user=user, broker=BrokerAccount.Broker.ALPACA,
                    defaults={
                        "mode": BrokerAccount.Mode.PAPER,
                        "api_key_id_enc": encrypt_key("PKLOADTESTKEYID00000"),
                        "api_secret_enc": encrypt_key("loadtestsecretvalue000"),
                        "account_number": f"PALOAD{i:03d}",
                        "is_default": True,
                        "status": BrokerAccount.Status.CONNECTED,
                    },
                )

            access = issue_token_pair(user)["access"]

        users.append({
            "index": i,
            "email": email,
            "password": PASSWORD,
            "user_id": str(user.id),
            "strategy_id": str(strat.id),
            "webhook_secret": webhook_secret,
            "totp_secret": totp_secret,
            "access": access,
        })
        if (i + 1) % 25 == 0 or i + 1 == count:
            print(f"  seeded {i + 1}/{count}")
    return users


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed M11 load-test fixtures.")
    ap.add_argument("--count", type=int, default=int(os.environ.get("LT_COUNT", 100)))
    ap.add_argument("--prefix", default=os.environ.get("LT_PREFIX", "loadtest+"))
    broker = ap.add_mutually_exclusive_group()
    broker.add_argument("--with-broker", dest="with_broker", action="store_true", default=True)
    broker.add_argument("--no-broker", dest="with_broker", action="store_false")
    ap.add_argument("--purge", action="store_true", help="delete all matching users and exit")
    ap.add_argument("--base-url", default=os.environ.get("LT_BASE_URL", "http://localhost:8777"))
    ap.add_argument("--ws-url", default=os.environ.get("LT_WS_URL", "ws://localhost:8788"))
    ap.add_argument("--out", default=str(_HERE / "fixtures.json"))
    args = ap.parse_args()

    if args.purge:
        purge(args.prefix)
        return 0

    print(f"seeding {args.count} users (prefix={args.prefix!r}, broker={args.with_broker}) ...")
    users = seed(count=args.count, prefix=args.prefix, with_broker=args.with_broker)
    fixtures = {
        "base_url": args.base_url,
        "ws_url": args.ws_url,
        "count": len(users),
        "with_broker": args.with_broker,
        "users": users,
    }
    Path(args.out).write_text(json.dumps(fixtures, indent=2))
    print(f"wrote {args.out} ({len(users)} users). Access tokens are ~15 min TTL — "
          f"start the run promptly or re-seed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
