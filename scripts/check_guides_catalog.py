#!/usr/bin/env python3
"""Guard: the Guides catalog and assets/guides/*.html must agree exactly.

Why this exists
---------------
The Guides tab has two halves that can drift silently:

* ``frontend/src/app/features/guides/guides.catalog.ts`` — the only thing that
  puts an article on the index, allows its slug through the viewer, and places
  it in the prev/next chain.
* ``frontend/src/assets/guides/<slug>.html`` — the bytes the viewer fetches.

Drift is invisible at build time and fails only in a user's browser:

* catalog entry with no file  -> a card on the index that opens "not found";
* file with no catalog entry  -> an orphan article. That is the exact defect the
  M10.5 help index was written to prevent, and it came back the moment the list
  of slugs stopped being the list of files.

The check is static text/AST-free parsing (no Node, no Angular) so it runs in
milliseconds on every push.

Run:  python3 scripts/check_guides_catalog.py
Exit: 0 = in sync, 1 = drift (prints a GitHub Actions ::error:: annotation)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = REPO_ROOT / "frontend/src/app/features/guides/guides.catalog.ts"
ASSETS = REPO_ROOT / "frontend/src/assets/guides"
IMG_DIR = ASSETS / "img"

SLUG_RE = re.compile(r"^\s*slug:\s*'([a-z0-9-]+)'", re.MULTILINE)
# src="assets/guides/img/foo.png" inside a guide's HTML.
IMG_SRC_RE = re.compile(r'src="assets/guides/img/([^"]+)"')


def main() -> int:
    if not CATALOG.exists():
        print(f"::error::missing {CATALOG.relative_to(REPO_ROOT)}")
        return 1

    catalog_slugs = set(SLUG_RE.findall(CATALOG.read_text(encoding="utf-8")))
    file_slugs = {p.stem for p in ASSETS.glob("*.html")}

    missing_files = sorted(catalog_slugs - file_slugs)
    orphan_files = sorted(file_slugs - catalog_slugs)

    # Every <img> a guide references must exist, or the step illustration is a
    # broken-image icon in production and nothing fails before then.
    missing_images: list[str] = []
    for html in sorted(ASSETS.glob("*.html")):
        for name in IMG_SRC_RE.findall(html.read_text(encoding="utf-8")):
            if not (IMG_DIR / name).exists():
                missing_images.append(f"{html.name} -> img/{name}")

    if not missing_files and not orphan_files and not missing_images:
        print(
            f"guides catalog in sync ({len(catalog_slugs)} articles, "
            f"{len(list(IMG_DIR.glob('*'))) if IMG_DIR.exists() else 0} images)"
        )
        return 0

    if missing_files:
        print(
            "::error::guides.catalog.ts lists slugs with no "
            f"frontend/src/assets/guides/<slug>.html: {', '.join(missing_files)}. "
            "The index will link to a 'not found' page."
        )
    if orphan_files:
        print(
            "::error::frontend/src/assets/guides/ contains articles missing from "
            f"guides.catalog.ts: {', '.join(orphan_files)}. They are unreachable "
            "from the Guides index AND rejected by the viewer's allow-list."
        )
    if missing_images:
        print(
            "::error::guide HTML references screenshots that do not exist: "
            f"{'; '.join(missing_images)}. Regenerate with "
            "`node tools/guide-screenshots.mjs` from frontend/."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
