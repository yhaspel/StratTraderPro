"""M11 §7.8 — seed the current Terms of Service + Privacy Policy versions.

The acceptance flow (blocking modal on version bump) is INERT until a
``TermsDocument`` of each kind exists. This command is the operator step that
makes it live — run it once counsel has approved the drafts in
``docs/legal/terms-of-service.md`` / ``privacy-policy.md``. Idempotent per
(kind, version).

    python manage.py seed_terms --tos 1.0 --privacy 1.0
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.users.models import TermsDocument


class Command(BaseCommand):
    help = "Seed the current Terms of Service + Privacy Policy versions."

    def add_arguments(self, parser):
        parser.add_argument("--tos", default="1.0", help="Terms of Service version to make current.")
        parser.add_argument("--privacy", default="1.0", help="Privacy Policy version to make current.")

    def handle(self, *args, **opts):
        specs = [
            (TermsDocument.Kind.TERMS, opts["tos"], "/legal/terms", "See docs/legal/terms-of-service.md"),
            (TermsDocument.Kind.PRIVACY, opts["privacy"], "/legal/privacy", "See docs/legal/privacy-policy.md"),
        ]
        for kind, version, url, text in specs:
            doc, created = TermsDocument.objects.get_or_create(
                kind=kind, version=version, defaults={"url": url, "text": text},
            )
            verb = "created" if created else "exists"
            self.stdout.write(f"{kind} v{version}: {verb}")
        self.stdout.write(self.style.SUCCESS("Terms seeded — the acceptance flow is now live."))
