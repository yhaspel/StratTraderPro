"""``python manage.py load_strategies <path>``  — M03, plan §6.4.

Walks ``<path>`` one level deep. Each immediate sub-directory is treated as
ONE strategy. Looks for:

  * Exactly one ``*.pine`` file       — required.
  * One file matching ``*description*.txt`` (any case, dashes/underscores
    interchangeable) — required.
  * Optional ``*_Webhook.json`` or ``*webhook*.json`` — if absent, a default
    template is synthesized so system rows still get a usable webhook
    payload template (the per-user WebhookConfig still mints its own
    secret + schema at first GET).

Idempotent via SHA-256 — re-running with unchanged files is a no-op.

Exit codes:
    0 = success, all rows seeded/updated.
    1 = at least one strategy directory failed validation but the rest
        succeeded; non-zero so CI catches it.

Usage::

    python manage.py load_strategies /path/to/Trading_Strategies/top-strategies
    python manage.py load_strategies /path/to/dir --dry-run
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from apps.strategies import services
from apps.strategies.metrics import refresh_count_gauge
from apps.strategies.models import Strategy, StrategyFile

#: Sub-strings on these filenames take a folder out of contention. Keeps the
#: command from accidentally globbing readme.md or research.md.
_STRATEGY_DIR_INDICATOR = ("strategy",)


class Command(BaseCommand):
    help = "Seed or update system strategies from a directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            type=str,
            help="Absolute path to the Trading Strategies directory.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Walk the directory and report what would happen without writing.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        root = Path(opts["path"]).expanduser().resolve()
        dry_run = opts["dry_run"]

        if not root.exists() or not root.is_dir():
            raise CommandError(f"{root} is not a directory.")

        summary = services.SeedSummary(seeded=0, updated=0, skipped=0, errors=[])
        any_failed = False

        for sub in sorted(root.iterdir()):
            if not sub.is_dir() or sub.name.startswith("."):
                continue
            try:
                result = self._seed_one(sub, dry_run=dry_run)
            except CommandError as exc:
                summary.add_error(f"{sub.name}: {exc}")
                self.stderr.write(self.style.ERROR(f"FAIL  {sub.name}: {exc}"))
                any_failed = True
                continue

            if result is None:
                summary.skipped += 1
                self.stdout.write(self.style.WARNING(f"SKIP  {sub.name} (no .pine + description)"))
                continue

            kind, slug = result
            if kind == "seeded":
                summary.seeded += 1
                self.stdout.write(self.style.SUCCESS(f"NEW   {slug}"))
            elif kind == "updated":
                summary.updated += 1
                self.stdout.write(self.style.SUCCESS(f"UPD   {slug}"))
            else:
                summary.skipped += 1
                self.stdout.write(f"NOOP  {slug}")

        # Summary line — easy to grep in CI.
        self.stdout.write(self.style.NOTICE(
            f"\nload_strategies: seeded={summary.seeded} "
            f"updated={summary.updated} skipped={summary.skipped} "
            f"errors={len(summary.errors or [])}"
        ))

        if not dry_run:
            refresh_count_gauge()

        if any_failed:
            # Non-zero exit so CI flags it.
            raise CommandError("One or more strategies failed to seed (see above).")

    # ------------------------------------------------------------------
    def _seed_one(self, folder: Path, *, dry_run: bool):
        """Returns (kind, slug) where kind is 'seeded' | 'updated' | 'noop',
        OR None if folder is not a strategy folder.
        """
        pine_files = sorted(folder.glob("*.pine"))
        if not pine_files:
            return None

        # Description: prefer a file containing 'description' OR fall back to
        # strategy.md so we always have *something* to display.
        desc_file = self._find_description(folder)
        if desc_file is None:
            return None

        webhook_file = self._find_webhook(folder)  # optional

        # The slug is derived from the folder name so the catalogue is stable
        # across renames of the inner pine file.
        slug = slugify(folder.name)[:64] or pine_files[0].stem
        # Display name: folder name with leading numeric prefix stripped.
        name = re.sub(r"^\d{1,3}[-_\s]+", "", folder.name).replace("-", " ").replace("_", " ").strip()
        name = name.title()[:64] or slug

        pine = pine_files[0]
        pine_bytes = pine.read_bytes()
        desc_bytes = desc_file.read_bytes()
        if webhook_file is not None:
            webhook_bytes = webhook_file.read_bytes()
            try:
                # Sanity: parses?
                json.loads(webhook_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CommandError(
                    f"webhook file {webhook_file.name} is not valid UTF-8 JSON: {exc}"
                ) from exc
            webhook_filename = webhook_file.name
        else:
            # Synthesize a default webhook template for this strategy.
            webhook_template = services.default_payload_template(slug)
            webhook_bytes = (json.dumps(webhook_template, indent=2) + "\n").encode("utf-8")
            webhook_filename = f"{slug}_Webhook.json"

        # Description short = first non-empty, non-tag line, ≤256 chars.
        desc_short = self._derive_short_description(desc_bytes)

        if dry_run:
            self.stdout.write(
                f"DRY   {slug}: pine={pine.name} desc={desc_file.name} "
                f"webhook={webhook_filename} ({len(pine_bytes)}B/{len(desc_bytes)}B/{len(webhook_bytes)}B)"
            )
            return ("noop", slug)

        existing_before = Strategy.objects.filter(owner=None, slug=slug).first()
        had_files_before = existing_before and set(
            existing_before.files.values_list("kind", flat=True)
        )

        strategy, changed = services.upsert_system_strategy(
            slug=slug,
            name=name,
            description_short=desc_short,
            pine_filename=pine.name,
            pine_bytes=pine_bytes,
            desc_filename=desc_file.name,
            desc_bytes=desc_bytes,
            webhook_filename=webhook_filename,
            webhook_bytes=webhook_bytes,
        )

        if existing_before is None:
            return ("seeded", slug)
        if changed:
            return ("updated", slug)
        return ("noop", slug)

    @staticmethod
    def _find_description(folder: Path) -> Path | None:
        # Prefer txt files containing 'description' in the name.
        for cand in sorted(folder.glob("*.txt")):
            if "description" in cand.name.lower():
                return cand
        # Fallback: strategy.md if present.
        md = folder / "strategy.md"
        if md.exists():
            return md
        return None

    @staticmethod
    def _find_webhook(folder: Path) -> Path | None:
        for cand in sorted(folder.glob("*.json")):
            if "webhook" in cand.name.lower():
                return cand
        return None

    @staticmethod
    def _derive_short_description(blob: bytes) -> str:
        text = blob.decode("utf-8", errors="replace")
        # Strip bbcode tags + markdown headers, take first non-empty line.
        text = re.sub(r"\[/?[a-z]+\]", "", text, flags=re.IGNORECASE)
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue  # markdown header
            return line[:256]
        return ""
