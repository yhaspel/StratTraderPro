"""News fetchers (M07 §6.1).

One fetcher per source implementing ``fetch_since(since) -> list[RawArticle]``.
FMP uses the (mockable) M06 FMPClient; the RSS-based sources use feedparser.
All network is injectable so CI runs against fixtures — no live keys/feeds.
Per-source ToS review is a deferred manual step (plan review note).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import NewsArticle

# feedparser fetches over urllib with no timeout and the default UA (SEC EDGAR
# fair-access blocks it). Fetch bytes ourselves with a bounded timeout and a
# descriptive, contactable User-Agent, then hand the bytes to feedparser (FIX-M4).
FEED_TIMEOUT = 10.0
FEED_USER_AGENT = (
    "StratTraderPro/1.0 (+https://strattraderpro.com; news-ingest contact: ops@strattraderpro.com)"
)


@dataclass
class RawArticle:
    source: str
    title: str
    url: str = ""
    body: str = ""
    published_at: object = None
    symbols: list = field(default_factory=list)


class FMPNewsFetcher:
    source = NewsArticle.Source.FMP

    def __init__(self, client=None):
        self._client = client

    def _fmp(self):
        if self._client is None:
            from apps.marketdata.fmp import FMPClient

            self._client = FMPClient()
        return self._client

    def fetch_since(self, since=None) -> list[RawArticle]:
        data = self._fmp().get("/news/stock-latest", {"limit": 100}, cache_ttl=30)
        out = []
        for r in data or []:
            sym = r.get("symbol") or r.get("tickers")
            symbols = [sym] if isinstance(sym, str) and sym else (sym or [])
            out.append(RawArticle(
                source=self.source,
                title=r.get("title", ""),
                url=r.get("url", ""),
                body=r.get("text", r.get("content", "")),
                published_at=r.get("publishedDate") or r.get("date"),
                symbols=[s for s in symbols if s],
            ))
        return out


class RSSFetcher:
    def __init__(self, source: str, feed_url: str, *, high_impact: bool = False, http=None):
        self.source = source
        self.feed_url = feed_url
        self.high_impact = high_impact
        self._http = http  # injectable for tests

    def fetch_since(self, since=None) -> list[RawArticle]:
        import feedparser

        feed = feedparser.parse(self._fetch_bytes())
        return self.entries_to_articles(feed.get("entries", []))

    def _fetch_bytes(self) -> bytes:
        import httpx

        headers = {"User-Agent": FEED_USER_AGENT}
        if self._http is not None:
            resp = self._http.get(self.feed_url, headers=headers)
            resp.raise_for_status()
            return resp.content
        with httpx.Client(timeout=FEED_TIMEOUT, headers=headers, follow_redirects=True) as client:
            resp = client.get(self.feed_url)
            resp.raise_for_status()
            return resp.content

    def entries_to_articles(self, entries) -> list[RawArticle]:
        out = []
        for e in entries or []:
            out.append(RawArticle(
                source=self.source,
                title=e.get("title", ""),
                url=e.get("link", ""),
                body=e.get("summary", e.get("description", "")),
                published_at=e.get("published") or e.get("updated"),
            ))
        return out


def build_fetchers():
    """The default source set (RSS URLs are placeholders until ToS review).

    Finnhub is intentionally excluded: its ``/api/v1/news`` is a token-required
    JSON endpoint, not a feed — feedparser never yields entries from it, so
    presenting it as a working source was misleading (FIX-M6). Re-add only behind
    a real JSON client.
    """
    S = NewsArticle.Source
    return [
        FMPNewsFetcher(),
        RSSFetcher(S.EDGAR, "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=8-K&output=atom"),
        RSSFetcher(S.NASDAQ_HALTS, "http://www.nasdaqtrader.com/rss.aspx?feed=tradehalts", high_impact=True),
        RSSFetcher(S.BENZINGA, "https://www.benzinga.com/feed"),
    ]
