"""Sentiment ingest helpers (M07 §6.1) — dedup, HTML strip, persistence."""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

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


def dedup_hash(url: str, title: str) -> str:
    return hashlib.sha256(f"{(url or '').strip()}|{(title or '').strip().lower()}".encode()).hexdigest()


def symbols_text(symbols) -> str:
    """Space-padded ' AAPL MSFT ' for a cross-DB exact-symbol text filter."""
    return " " + " ".join(symbols) + " " if symbols else ""


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
    published = raw.published_at
    if isinstance(published, str):
        published = parse_datetime(published)
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
