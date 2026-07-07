"""Symbol tagger (M07 §6.2).

Regex-against-registry primary pass (high precision — only tickers present in
``TickerRegistry`` count) + ``$CASHTAG`` mentions + an alias pass
(``AliasTable``: "apple inc" → AAPL). The optional spaCy NER second pass is a
lazy, flag-gated enhancement (heavy dep — worker-image only); CI uses the
regex/registry/alias path which is deterministic and test-friendly.
"""
from __future__ import annotations

import re

from django.conf import settings

# Uppercase words that are never tickers (reduce false positives).
_STOPWORD_TICKERS = {
    "A", "I", "THE", "CEO", "CFO", "USA", "US", "ETF", "IPO", "NYSE", "AI", "EPS",
    "GDP", "FED", "SEC", "FDA", "EU", "UK", "Q1", "Q2", "Q3", "Q4", "IT",
    "OK", "PR", "TV", "URL", "FAQ", "AM", "PM", "EST", "EDT", "GMT",
}
_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
_UPPER_RE = re.compile(r"\b[A-Z]{1,5}\b")


def _known(candidates: set[str]) -> set[str]:
    from .models import TickerRegistry

    if not candidates:
        return set()
    return set(
        TickerRegistry.objects.filter(symbol__in=candidates).values_list("symbol", flat=True)
    )


def tag_symbols(text: str, *, hint_symbols=None) -> list[str]:
    text = text or ""
    symbols: set[str] = {s.upper().strip() for s in (hint_symbols or []) if s}

    # $CASHTAG — deliberate ticker mention, always accepted.
    for m in _CASHTAG_RE.findall(text):
        symbols.add(m.upper())

    # Uppercase tokens, filtered to registry-known tickers (precision).
    candidates = {t for t in _UPPER_RE.findall(text) if t not in _STOPWORD_TICKERS}
    symbols |= _known(candidates)

    # Alias pass (company names → symbol).
    if getattr(settings, "SENTIMENT_ALIAS_TAGGING", True):
        from .models import AliasTable

        lower = text.lower()
        for alias, symbol in AliasTable.objects.values_list("alias", "symbol"):
            if alias and alias in lower:
                symbols.add(symbol)

    # Optional spaCy NER (worker-image only; lazy).
    if getattr(settings, "SENTIMENT_SPACY_NER", False):  # pragma: no cover — heavy dep
        symbols |= _spacy_symbols(text)

    return sorted(symbols)


def _spacy_symbols(text: str) -> set[str]:  # pragma: no cover — worker-only
    try:

        nlp = _load_spacy()
        from .models import AliasTable

        out = set()
        for ent in nlp(text[:2000]).ents:
            if ent.label_ in ("ORG",):
                row = AliasTable.objects.filter(alias=ent.text.lower()).first()
                if row:
                    out.add(row.symbol)
        return out
    except Exception:
        return set()


_SPACY = None


def _load_spacy():  # pragma: no cover — worker-only
    global _SPACY
    if _SPACY is None:
        import spacy

        _SPACY = spacy.load("en_core_web_sm")
    return _SPACY
