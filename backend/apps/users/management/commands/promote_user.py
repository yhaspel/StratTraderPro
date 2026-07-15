"""Promote an account to staff/superuser and optionally prune all other users.

On a single-tenant self-hosted instance this is the bootstrap path for admin
access: the M10 admin portal is ``is_staff``-gated, so a fresh instance has no
way to grant the first staff account through the UI. It also keeps the instance
a single account, via ``--remove-others``.

Deletion goes through the ORM (``QuerySet.delete()``), so Django cascades the
related rows and fires signals — unlike a raw SQL ``DELETE`` against
``users_user``, which can trip foreign keys or leave the audit chain dangling.

    # Promote only (idempotent, non-destructive)
    python manage.py promote_user owner@example.com --staff --superuser

    # Promote AND make it the only account (non-interactive)
    python manage.py promote_user owner@example.com --staff --superuser \\
        --remove-others --yes
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Set is_staff/is_superuser on an account and optionally remove all others."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email of the account to keep/promote.")
        parser.add_argument("--staff", action="store_true", help="Set is_staff=True.")
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Set is_superuser=True (also sets is_staff).",
        )
        parser.add_argument(
            "--remove-others",
            action="store_true",
            help="Delete every OTHER account (ORM cascade). Prompts unless --yes.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip the deletion confirmation prompt (for non-interactive use).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing anything.",
        )

    def handle(self, *args, **opts):
        User = get_user_model()
        email = opts["email"].strip()
        want_staff = opts["staff"] or opts["superuser"]
        want_super = opts["superuser"]

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist as exc:
            raise CommandError(f"No account with email {email!r} — nothing changed.") from exc
        except User.MultipleObjectsReturned as exc:
            raise CommandError(f"Multiple accounts match {email!r} — refusing to guess.") from exc

        others = User.objects.exclude(pk=user.pk)
        others_count = others.count()

        self.stdout.write(f"Keep/promote : {user.email} (id={user.pk})")
        self.stdout.write(f"  is_staff     {user.is_staff} -> {user.is_staff or want_staff}")
        self.stdout.write(f"  is_superuser {user.is_superuser} -> {user.is_superuser or want_super}")
        if opts["remove_others"]:
            self.stdout.write(f"Delete {others_count} other account(s):")
            for other in others:
                self.stdout.write(f"  - {other.email} (id={other.pk})")

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — nothing written."))
            return

        if opts["remove_others"] and others_count and not opts["yes"]:
            answer = input(f"Permanently delete {others_count} other account(s)? Type 'yes': ")
            if answer.strip().lower() != "yes":
                raise CommandError("Aborted — nothing changed.")

        with transaction.atomic():
            changed = []
            if want_staff and not user.is_staff:
                user.is_staff = True
                changed.append("is_staff")
            if want_super and not user.is_superuser:
                user.is_superuser = True
                changed.append("is_superuser")
            if changed:
                user.save(update_fields=changed)
            if opts["remove_others"] and others_count:
                User.objects.exclude(pk=user.pk).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {user.email} promoted (changed: {', '.join(changed) or 'nothing'}); "
                f"removed {others_count if opts['remove_others'] else 0} other account(s)."
            )
        )
        remaining = list(
            User.objects.order_by("email").values_list("email", "is_staff", "is_superuser")
        )
        self.stdout.write(f"Accounts now: {remaining}")
