"""Sentiment ingest helpers (M07 §6.1) — dedup, HTML strip, persistence."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from datetime import timezone as dt_timezone
from html.parser import HTMLParser

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import NewsArticle
from .tagger import tag_symbols

_MATERIAL_RE = re.compile(r"\b(8-K|halt(ed)?|guidance|profit warning|bankruptcy|SEC filing)\b", re.I)


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data):
        self._chunks.append(data)

    @property
    def text(self) -> str:
        return " ".join("".join(self._chunks).split())


def strip_html(html: str) -> str:
    if not html:
        return ""
    p = _Stripper()
    try:
        p.feed(html)
    except Exception:  # pragma: no cover — malformed HTML
        return re.sub(r"<[^>]+>", " ", html)
    return p.text


def _parse_published(value):
    """Parse a published timestamp to a tz-aware datetime, or None.

    RSS feeds emit RFC-822 dates ("Mon, 07 Jul 2026 19:00:00 GMT") on which
    ``parse_datetime`` returns None — every RSS article then sorted into limbo.
    Fall back to ``email.utils.parsedate_to_datetime`` and make it aware (FIX-M5).
    """
    if isinstance(value, str):
        dt = parse_datetime(value)
        if dt is None:
            from email.utils import parsedate_to_datetime

            try:
                dt = parsedate_to_datetime(value)
            except (TypeError, ValueError, IndexError):
                dt = None
        value = dt
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, dt_timezone.utc)
        return value
    return None


def dedup_hash(url: str, title: str) -> str:
    return hashlib.sha256(f"{(url or '').strip()}|{(title or '').strip().lower()}".encode()).hexdigest()


def symbols_text(symbols) -> str:
    """Space-padded ' AAPL MSFT ' for a cross-DB exact-symbol text filter. Capped
    to keep within the field width (avoids a Postgres DataError + mid-symbol cut)."""
    return " " + " ".join(symbols[:24]) + " " if symbols else ""


def is_material(source: str, title: str, body: str) -> bool:
    if source in (NewsArticle.Source.EDGAR, NewsArticle.Source.NASDAQ_HALTS):
        return True
    return bool(_MATERIAL_RE.search(f"{title} {body[:400]}"))


def ingest_article(raw) -> tuple[NewsArticle | None, bool]:
    """Persist one RawArticle with dedup. Returns (article, created)."""
    title = (raw.title or "").strip()[:512]
    if not title:
        return None, False
    body = strip_html(raw.body or "")[:20000]
    h = dedup_hash(raw.url, title)
    symbols = tag_symbols(f"{title}. {body[:600]}", hint_symbols=getattr(raw, "symbols", None))
    material = is_material(raw.source, title, body)
    published = _parse_published(raw.published_at)
    obj, created = NewsArticle.objects.get_or_create(
        dedup_hash=h,
        defaults={
            "source": raw.source,
            "url": (raw.url or "")[:1000],
            "title": title,
            "body": body,
            "symbols": symbols,
            "symbols_text": symbols_text(symbols),
            "material": material,
            "published_at": published,
        },
    )
    return obj, created
