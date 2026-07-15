"""Seed the current Terms of Service + Privacy Policy versions.

The acceptance flow (blocking modal on version bump) is INERT until a
``TermsDocument`` of each kind exists — so on a single-user self-hosted
instance you never need to run this. If you choose to run a multi-user
instance, supply your OWN terms/privacy text (StratTraderPro ships none) and
seed it here. Idempotent per (kind, version).

    python manage.py seed_terms --tos 1.0 --privacy 1.0 \\
        --tos-url https://example.com/terms --privacy-url https://example.com/privacy
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.users.models import TermsDocument


class Command(BaseCommand):
    help = "Seed the current Terms of Service + Privacy Policy versions."

    def add_arguments(self, parser):
        parser.add_argument("--tos", default="1.0", help="Terms of Service version to make current.")
        parser.add_argument("--privacy", default="1.0", help="Privacy Policy version to make current.")
        parser.add_argument("--tos-url", default="/legal/terms", help="URL of your Terms of Service.")
        parser.add_argument("--privacy-url", default="/legal/privacy", help="URL of your Privacy Policy.")

    def handle(self, *args, **opts):
        specs = [
            (TermsDocument.Kind.TERMS, opts["tos"], opts["tos_url"], "Operator-supplied Terms of Service."),
            (TermsDocument.Kind.PRIVACY, opts["privacy"], opts["privacy_url"], "Operator-supplied Privacy Policy."),
        ]
        for kind, version, url, text in specs:
            doc, created = TermsDocument.objects.get_or_create(
                kind=kind, version=version, defaults={"url": url, "text": text},
            )
            verb = "created" if created else "exists"
            self.stdout.write(f"{kind} v{version}: {verb}")
        self.stdout.write(self.style.SUCCESS("Terms seeded — the acceptance flow is now live."))
