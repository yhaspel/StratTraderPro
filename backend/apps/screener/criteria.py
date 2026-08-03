"""``[screen]`` block grammar + deterministic parser (M16 §6.1).

A strategy author writes ONE optional ``[screen]`` block anywhere inside the
TradingView-style DESC file; this module turns it into vendor params + derived
criteria, or into a list of line-numbered errors.

**Pure stdlib — no Django imports.** The views, the Celery task and the tests
all import it, and keeping it framework-free means the grammar can be unit
tested without a settings module.

Security posture (§11): the block is user-authored input that arrives inside a
description of up to 256KB (#49). Every scan below is linear —
``re.finditer`` over *literal* tag patterns and a single pass over the body's
lines. There is no backtracking-prone regex anywhere in this file, and the
size/line caps are applied BEFORE any per-line work. Values are never eval'd
and never interpolated into a URL by hand (the client passes them through
``httpx``'s ``params=`` encoder).

Line numbers in errors are 1-based **within the whole description**, not within
the block, so an author can jump straight to the offending line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Caps applied pre-parse (§6.1 / §11).
MAX_BLOCK_BYTES = 4096
MAX_BLOCK_LINES = 40

# Enrichment + vendor limit bounds (§6.1; §11 "limit <= 100").
LIMIT_MIN = 1
LIMIT_MAX = 100
LIMIT_DEFAULT = 50

# Default bar history required once any derived key is in play (§6.1).
MIN_HISTORY_DEFAULT = 260
MIN_HISTORY_MAX = 2000

# The two SMA windows the derived stage knows how to compute (§6.1).
SMA_WINDOWS = (50, 200)

# Longest accepted value for a free-text vendor enum (sector/industry/...).
MAX_STRING_LEN = 64

# Literal, non-backtracking tag patterns. Case-insensitive per §6.1.
_OPEN_RE = re.compile(r"\[screen\]", re.IGNORECASE)
_CLOSE_RE = re.compile(r"\[/screen\]", re.IGNORECASE)

# Numeric literal with an optional K/M/B/T magnitude suffix. Anchored and
# fully deterministic — every branch is a bounded character class.
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?([KMBT]?)$", re.IGNORECASE)
_SUFFIX = {"": 1, "K": 10**3, "M": 10**6, "B": 10**9, "T": 10**12}

# key -> the FMP param stem for its >=/<= halves (§6.1 mapping table).
_RANGE_KEYS = {
    "market_cap": "marketCap",
    "price": "price",
    "volume": "volume",
    "beta": "beta",
    "dividend": "dividend",
}
# key -> FMP param name, passed through as a single string.
_STRING_KEYS = {
    "sector": "sector",
    "industry": "industry",
    "exchange": "exchange",
    "country": "country",
}
_DERIVED_KEYS = ("above_sma", "sma_rising", "near_52w_high", "min_history")
_REPEATABLE = ("above_sma", "sma_rising")

ALL_KEYS = (
    tuple(_RANGE_KEYS) + tuple(_STRING_KEYS) + ("etf",) + _DERIVED_KEYS + ("limit",)
)


@dataclass(frozen=True)
class ScreenCriteria:
    """One parsed ``[screen]`` block.

    ``criteria`` is the author-facing normalized snapshot (what the panel shows
    as chips and what the run row stores for reproducibility); ``vendor_params``
    is what goes on the wire to ``/company-screener``; ``derived`` is what the
    local enrichment pass applies.
    """

    criteria: dict = field(default_factory=dict)
    vendor_params: dict = field(default_factory=dict)
    derived: dict = field(default_factory=dict)
    limit: int = LIMIT_DEFAULT


class ScreenCriteriaError(Exception):
    """Raised by :func:`parse_or_raise` with ``.errors`` = [{line, error}]."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(f"{len(errors)} error(s) in [screen] block")


def _line_of(text: str, index: int) -> int:
    """1-based line number of ``index`` in ``text`` (linear count of newlines)."""
    return text.count("\n", 0, index) + 1


def _parse_number(token: str):
    """``"2B"`` -> ``2000000000``. Returns ``None`` when ``token`` is not a
    number. Integral results come back as ``int`` so the JSON snapshot and the
    vendor params carry ``2000000000``, not ``2000000000.0``."""
    m = _NUMBER_RE.match(token)
    if not m:
        return None
    suffix = m.group(1).upper()
    body = token[: len(token) - len(m.group(1))] if suffix else token
    try:
        value = float(body) * _SUFFIX[suffix]
    except ValueError:  # pragma: no cover — the regex already constrains this
        return None
    return int(value) if value == int(value) else value


def extract_block(text: str) -> tuple[str | None, int, list[dict]]:
    """Locate the single ``[screen]`` block.

    Returns ``(body, first_body_line, errors)``. ``body`` is ``None`` when the
    description simply has no block (a normal, non-error state — AC-16-4 turns
    it into ``block_present: false``, never a parse failure).
    """
    opens = list(_OPEN_RE.finditer(text))
    if not opens:
        return None, 0, []

    start = opens[0]
    if len(opens) > 1:
        return None, 0, [{
            "line": _line_of(text, opens[1].start()),
            "error": "A description may contain only one [screen] block (duplicate_block).",
        }]

    close = _CLOSE_RE.search(text, start.end())
    if close is None:
        return None, 0, [{
            "line": _line_of(text, start.start()),
            "error": "Unclosed [screen] block — add a [/screen] line to close it.",
        }]

    body = text[start.end():close.start()]
    # The body's first line is the line the opening tag sits on, +1 when the
    # tag is followed by a newline (the normal, readable authoring shape).
    first_line = _line_of(text, start.end())
    return body, first_line, []


def parse(text: str) -> tuple[ScreenCriteria | None, list[dict]]:
    """Parse ``text`` (a whole DESC file) into criteria.

    Returns ``(criteria, errors)``. ``(None, [])`` means "no block present";
    ``(None, [...])`` means the block is malformed; ``(criteria, [])`` is a
    clean parse.
    """
    if not text:
        return None, []
    # Strip a UTF-8 BOM — real TradingView exports carry one (the #45 lesson).
    if text.startswith("﻿"):
        text = text[1:]

    body, first_line, errors = extract_block(text)
    if errors:
        return None, errors
    if body is None:
        return None, []

    # ---- caps BEFORE any per-line work (§11) ----------------------------
    if len(body.encode("utf-8")) > MAX_BLOCK_BYTES:
        return None, [{
            "line": first_line,
            "error": f"[screen] block is larger than {MAX_BLOCK_BYTES} bytes.",
        }]
    raw_lines = body.split("\n")
    if len(raw_lines) > MAX_BLOCK_LINES:
        return None, [{
            "line": first_line,
            "error": f"[screen] block has more than {MAX_BLOCK_LINES} lines.",
        }]

    return _parse_body(raw_lines, first_line)


def _parse_body(raw_lines: list[str], first_line: int):
    errors: list[dict] = []
    criteria: dict = {}
    seen_scalar: set[str] = set()

    for offset, raw in enumerate(raw_lines):
        lineno = first_line + offset
        line = raw.rstrip("\r").strip()  # CRLF exports are the norm, not the exception
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            errors.append({"line": lineno, "error": f"Expected 'key: value', got {line!r}."})
            continue
        raw_key, _, raw_val = line.partition(":")
        key = raw_key.strip().lower()
        val = raw_val.strip()

        if key not in ALL_KEYS:
            errors.append({
                "line": lineno,
                "error": f"Unknown key {key!r}. Valid keys: {', '.join(sorted(ALL_KEYS))}.",
            })
            continue
        if not val:
            errors.append({"line": lineno, "error": f"Key {key!r} has no value."})
            continue
        if key not in _REPEATABLE:
            if key in seen_scalar:
                errors.append({"line": lineno, "error": f"Duplicate key {key!r} (duplicate_key)."})
                continue
            seen_scalar.add(key)

        err = _apply(key, val, criteria, lineno)
        if err:
            errors.append(err)

    if errors:
        return None, errors
    return _build(criteria), []


def _apply(key: str, val: str, criteria: dict, lineno: int) -> dict | None:
    """Validate + fold one ``key: value`` into ``criteria``. Returns an error dict."""
    if key in _RANGE_KEYS:
        parsed, err = _parse_range(val)
        if err:
            return {"line": lineno, "error": f"{key}: {err}"}
        criteria[key] = parsed
        return None

    if key in _STRING_KEYS:
        if "|" in val or "," in val:
            return {"line": lineno, "error": (
                f"{key}: only ONE value is supported in v1 — "
                "multi-value vendor enums are out of scope."
            )}
        if len(val) > MAX_STRING_LEN:
            return {"line": lineno, "error": f"{key}: value longer than {MAX_STRING_LEN} characters."}
        if key == "country":
            if not (len(val) == 2 and val.isalpha()):
                return {"line": lineno, "error": "country: expected a 2-letter ISO code, e.g. US."}
            criteria[key] = val.upper()
            return None
        criteria[key] = val
        return None

    if key == "etf":
        low = val.lower()
        if low not in ("true", "false"):
            return {"line": lineno, "error": "etf: expected true or false."}
        criteria[key] = low == "true"
        return None

    if key in ("above_sma", "sma_rising"):
        num = _parse_number(val)
        if num not in SMA_WINDOWS:
            return {"line": lineno, "error": (
                f"{key}: expected one of {', '.join(str(w) for w in SMA_WINDOWS)}."
            )}
        bucket = criteria.setdefault(key, [])
        if num in bucket:
            return {"line": lineno, "error": f"{key}: {num} is already set (duplicate_key)."}
        bucket.append(num)
        bucket.sort()
        return None

    if key == "near_52w_high":
        num = _parse_number(val[:-1].strip() if val.endswith("%") else val)
        if num is None:
            return {"line": lineno, "error": "near_52w_high: expected a percentage, e.g. 25%."}
        if not (1 <= num <= 100):
            return {"line": lineno, "error": "near_52w_high: percentage must be between 1 and 100."}
        criteria[key] = num
        return None

    if key == "min_history":
        num = _parse_number(val)
        if num is None or int(num) != num or not (1 <= num <= MIN_HISTORY_MAX):
            return {"line": lineno, "error": (
                f"min_history: expected a whole number of days between 1 and {MIN_HISTORY_MAX}."
            )}
        criteria[key] = int(num)
        return None

    # key == "limit" — out-of-range CLAMPS rather than erroring (§11 bounds the
    # vendor spend; an over-eager limit is not an authoring mistake worth
    # failing the whole block for).
    num = _parse_number(val)
    if num is None or int(num) != num:
        return {"line": lineno, "error": "limit: expected a whole number between 1 and 100."}
    criteria["limit"] = max(LIMIT_MIN, min(LIMIT_MAX, int(num)))
    return None


def _parse_range(val: str) -> tuple[dict | None, str | None]:
    """``">= 2B"`` -> ``({"gte": 2000000000}, None)``; ``"10..1000"`` -> both ends."""
    if ".." in val:
        lo_s, _, hi_s = val.partition("..")
        lo, hi = _parse_number(lo_s.strip()), _parse_number(hi_s.strip())
        if lo is None or hi is None:
            return None, f"expected 'A..B' with numbers, got {val!r}."
        if lo > hi:
            return None, f"range is inverted ({lo_s.strip()}..{hi_s.strip()})."
        return {"gte": lo, "lte": hi}, None

    for op, field_name in ((">=", "gte"), ("<=", "lte")):
        if val.startswith(op):
            num = _parse_number(val[len(op):].strip())
            if num is None:
                return None, f"expected a number after {op}, got {val!r}."
            return {field_name: num}, None

    if val.startswith(">") or val.startswith("<"):
        return None, f"use '>=' or '<=' (inclusive), not {val[0]!r}."
    return None, f"expected '>= N', '<= N' or 'A..B', got {val!r}."


def _build(criteria: dict) -> ScreenCriteria:
    """Fold a validated criteria dict into vendor params + derived criteria."""
    limit = criteria.get("limit", LIMIT_DEFAULT)
    criteria = {**criteria, "limit": limit}

    vendor: dict = {}
    for key, stem in _RANGE_KEYS.items():
        bounds = criteria.get(key)
        if not bounds:
            continue
        if "gte" in bounds:
            vendor[f"{stem}MoreThan"] = bounds["gte"]
        if "lte" in bounds:
            vendor[f"{stem}LowerThan"] = bounds["lte"]
    for key, param in _STRING_KEYS.items():
        if key in criteria:
            vendor[param] = criteria[key]

    # Always-sent params. ``isActivelyTrading`` is spec'd as unconditional;
    # ``isEtf`` mirrors it per amendment A9 — sending it always is the
    # deterministic-narrowing reading of "default false" and removes the
    # ambiguity where §9's example omitted it.
    vendor["isActivelyTrading"] = True
    vendor["isEtf"] = bool(criteria.get("etf", False))
    vendor["limit"] = limit

    derived = {k: criteria[k] for k in ("above_sma", "sma_rising", "near_52w_high") if k in criteria}
    if derived or "min_history" in criteria:
        derived["min_history"] = criteria.get("min_history", MIN_HISTORY_DEFAULT)

    return ScreenCriteria(
        criteria=criteria, vendor_params=vendor, derived=derived, limit=limit,
    )


def parse_or_raise(text: str) -> ScreenCriteria | None:
    """``parse`` but raising :class:`ScreenCriteriaError` on a malformed block."""
    criteria, errors = parse(text)
    if errors:
        raise ScreenCriteriaError(errors)
    return criteria


def decode_desc(content) -> str:
    """DESC ``BinaryField`` bytes -> text, tolerating whatever the author
    uploaded (§ guardrails: UTF-8 with ``errors="replace"``)."""
    if content is None:
        return ""
    return bytes(content).decode("utf-8", errors="replace")
