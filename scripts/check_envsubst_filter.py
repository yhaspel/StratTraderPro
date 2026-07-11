#!/usr/bin/env python3
"""Guard: NGINX_ENVSUBST_FILTER must match the vars docker/nginx.conf.template emits.

Why this exists (BUG-004)
-------------------------
The nginx image substitutes ONLY the variables named in ``NGINX_ENVSUBST_FILTER``,
an anchored allowlist. The filter has to stay narrow so nginx's own runtime vars
(``$uri``, ``$host``, ``$remote_addr``, ...) survive — but any ``${VAR}`` in the
template that is *absent* from the filter is not substituted, and its literal text
is served to the browser.

That is precisely how M10 shipped: the filter said ``^BACKEND_URL$`` while the
template emitted five variables, so the SPA was served

    window.STP_CONFIG = { ..., sentryDsn: '${SENTRY_DSN}', ... }

`Sentry.init({dsn: '${SENTRY_DSN}'})` does not throw on an invalid DSN — it just
becomes a no-op. Frontend Sentry therefore reported nothing, for months, with a
green build. Nothing caught it because the E2E smoke runs `ng serve`, not the
nginx image, so the production artifact was never exercised.

This check is deliberately *static* (no Docker, milliseconds) so it can run on
every push. It enforces an exact set equality in both directions:

* a template var missing from the filter  -> ships `${...}` to users  (dangerous)
* a filter var absent from the template   -> dead config, i.e. drift  (a smell)

Run:  python3 scripts/check_envsubst_filter.py
Exit: 0 = in sync, 1 = drift (prints a GitHub Actions ::error:: annotation)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "docker" / "nginx.conf.template"
DOCKERFILE = REPO_ROOT / "docker" / "frontend.Dockerfile"

# `${FOO}` — braced only. nginx's own vars in the template are bare (`$uri`,
# `$host`, `$remote_addr`), so they are correctly ignored here.
TEMPLATE_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

# ENV NGINX_ENVSUBST_FILTER='^(A|B)$'   /   ENV NGINX_ENVSUBST_FILTER='^A$'
FILTER_RE = re.compile(r"NGINX_ENVSUBST_FILTER=['\"]([^'\"]+)['\"]")


def strip_comments(text: str) -> str:
    """Drop nginx comment lines.

    The template's comments *talk about* this mechanism and necessarily contain
    example placeholders like ``${FOO}``. Without this, the guard reports its own
    documentation as a violation — which it did on the first run.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def template_vars(text: str) -> set[str]:
    return set(TEMPLATE_VAR_RE.findall(strip_comments(text)))


def filter_vars(text: str) -> set[str]:
    m = FILTER_RE.search(text)
    if not m:
        raise SystemExit(
            f"::error::NGINX_ENVSUBST_FILTER not found in {DOCKERFILE.relative_to(REPO_ROOT)}"
        )
    pattern = m.group(1)
    # Strip the anchors and any wrapping group: ^(A|B)$ -> A|B ; ^A$ -> A
    body = pattern.strip()
    body = body.removeprefix("^").removesuffix("$")
    body = body.strip()
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    return {part.strip() for part in body.split("|") if part.strip()}


def main() -> int:
    tpl = template_vars(TEMPLATE.read_text())
    flt = filter_vars(DOCKERFILE.read_text())

    missing = sorted(tpl - flt)  # emitted but never substituted -> "${FOO}" to the browser
    extra = sorted(flt - tpl)  # allowlisted but unused -> drift

    if not missing and not extra:
        print(f"envsubst filter in sync ({len(tpl)} vars): {', '.join(sorted(tpl))}")
        return 0

    if missing:
        print(
            "::error::docker/nginx.conf.template emits variables that are NOT in "
            f"NGINX_ENVSUBST_FILTER: {', '.join(missing)}. They will be served to the "
            'browser as the literal string "${...}" (this is BUG-004 — it is how '
            "frontend Sentry silently never worked). Add them to the filter in "
            "docker/frontend.Dockerfile."
        )
    if extra:
        print(
            "::error::NGINX_ENVSUBST_FILTER allowlists variables the template does not "
            f"emit: {', '.join(extra)}. Remove them, or add them to the template."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
