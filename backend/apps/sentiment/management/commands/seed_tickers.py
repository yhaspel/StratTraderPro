"""RISK-5 — seed the sentiment ``TickerRegistry`` + ``AliasTable``.

The tagger (apps/sentiment/tagger.py) resolves article symbols via cashtags,
the registry, and the alias table. In every deployed config that table is empty
(it is only ever populated in tests), so market sentiment is permanently 0.00
even with real scorers. This idempotent command seeds a large-cap S&P-500 core
(symbol + company-name aliases) so the pipeline CAN produce non-zero output once
real scoring is enabled (SENTIMENT_FAKE_SCORERS=False).

Run:  python manage.py seed_tickers
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.sentiment.models import AliasTable, TickerRegistry

# (symbol, company name, is_etf). Large-cap S&P-500 core + the most-referenced
# broad-market ETFs. Extend freely — get_or_create keeps this idempotent.
TICKERS: list[tuple[str, str, bool]] = [
    ("AAPL", "Apple Inc", False), ("MSFT", "Microsoft Corporation", False),
    ("AMZN", "Amazon.com Inc", False), ("NVDA", "NVIDIA Corporation", False),
    ("GOOGL", "Alphabet Inc", False), ("GOOG", "Alphabet Inc", False),
    ("META", "Meta Platforms Inc", False), ("TSLA", "Tesla Inc", False),
    ("BRK.B", "Berkshire Hathaway Inc", False), ("JPM", "JPMorgan Chase & Co", False),
    ("V", "Visa Inc", False), ("MA", "Mastercard Incorporated", False),
    ("UNH", "UnitedHealth Group Incorporated", False), ("XOM", "Exxon Mobil Corporation", False),
    ("JNJ", "Johnson & Johnson", False), ("LLY", "Eli Lilly and Company", False),
    ("PG", "Procter & Gamble Company", False), ("HD", "Home Depot Inc", False),
    ("AVGO", "Broadcom Inc", False), ("MRK", "Merck & Co Inc", False),
    ("COST", "Costco Wholesale Corporation", False), ("ABBV", "AbbVie Inc", False),
    ("PEP", "PepsiCo Inc", False), ("KO", "Coca-Cola Company", False),
    ("ADBE", "Adobe Inc", False), ("WMT", "Walmart Inc", False),
    ("CRM", "Salesforce Inc", False), ("BAC", "Bank of America Corporation", False),
    ("MCD", "McDonald's Corporation", False), ("CSCO", "Cisco Systems Inc", False),
    ("ACN", "Accenture plc", False), ("NFLX", "Netflix Inc", False),
    ("AMD", "Advanced Micro Devices Inc", False), ("LIN", "Linde plc", False),
    ("TMO", "Thermo Fisher Scientific Inc", False), ("ABT", "Abbott Laboratories", False),
    ("ORCL", "Oracle Corporation", False), ("DIS", "Walt Disney Company", False),
    ("WFC", "Wells Fargo & Company", False), ("INTC", "Intel Corporation", False),
    ("QCOM", "QUALCOMM Incorporated", False), ("TXN", "Texas Instruments Incorporated", False),
    ("IBM", "International Business Machines Corporation", False), ("GE", "General Electric Company", False),
    ("CAT", "Caterpillar Inc", False), ("BA", "Boeing Company", False),
    ("PFE", "Pfizer Inc", False), ("NKE", "Nike Inc", False),
    ("PM", "Philip Morris International Inc", False), ("HON", "Honeywell International Inc", False),
    ("UNP", "Union Pacific Corporation", False), ("GS", "Goldman Sachs Group Inc", False),
    ("MS", "Morgan Stanley", False), ("AMGN", "Amgen Inc", False),
    ("SBUX", "Starbucks Corporation", False), ("INTU", "Intuit Inc", False),
    ("LOW", "Lowe's Companies Inc", False), ("BLK", "BlackRock Inc", False),
    ("ISRG", "Intuitive Surgical Inc", False), ("T", "AT&T Inc", False),
    ("VZ", "Verizon Communications Inc", False), ("CVX", "Chevron Corporation", False),
    ("SPGI", "S&P Global Inc", False), ("NOW", "ServiceNow Inc", False),
    ("BKNG", "Booking Holdings Inc", False), ("AXP", "American Express Company", False),
    ("DE", "Deere & Company", False), ("GILD", "Gilead Sciences Inc", False),
    ("MDT", "Medtronic plc", False), ("ADP", "Automatic Data Processing Inc", False),
    ("C", "Citigroup Inc", False), ("MMM", "3M Company", False),
    ("MU", "Micron Technology Inc", False), ("PLD", "Prologis Inc", False),
    ("REGN", "Regeneron Pharmaceuticals Inc", False), ("PYPL", "PayPal Holdings Inc", False),
    ("UBER", "Uber Technologies Inc", False), ("SCHW", "Charles Schwab Corporation", False),
    ("F", "Ford Motor Company", False), ("GM", "General Motors Company", False),
    ("PLTR", "Palantir Technologies Inc", False), ("COIN", "Coinbase Global Inc", False),
    # Broad-market / sector ETFs (is_etf=True; the tagger uses this flag).
    ("SPY", "SPDR S&P 500 ETF Trust", True), ("QQQ", "Invesco QQQ Trust", True),
    ("IWM", "iShares Russell 2000 ETF", True), ("DIA", "SPDR Dow Jones Industrial Average ETF", True),
    ("VOO", "Vanguard S&P 500 ETF", True), ("VTI", "Vanguard Total Stock Market ETF", True),
    ("XLK", "Technology Select Sector SPDR Fund", True), ("XLF", "Financial Select Sector SPDR Fund", True),
    ("XLE", "Energy Select Sector SPDR Fund", True), ("GLD", "SPDR Gold Shares", True),
]

# Corporate suffixes stripped to produce a shorter, human-referenced alias.
_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|corporation|corp|company|co|plc|holdings|group|trust|"
    r"fund|ltd|the|and|&)\b\.?",
    re.IGNORECASE,
)


def _aliases_for(name: str) -> set[str]:
    """Company-name aliases: the full lowercased name + a suffix-stripped short form."""
    full = name.strip().lower()
    short = _SUFFIX_RE.sub(" ", full)
    short = re.sub(r"[.,]", " ", short)
    short = re.sub(r"\s+", " ", short).strip()
    out = {full}
    if short and short != full and len(short) >= 3:
        out.add(short)
    return {a for a in out if a}


class Command(BaseCommand):
    help = "Seed the sentiment TickerRegistry + AliasTable with the S&P-500 large-cap core (RISK-5)."

    def handle(self, *args, **options):
        created_symbols = 0
        created_aliases = 0
        with transaction.atomic():
            for symbol, name, is_etf in TICKERS:
                _, was_created = TickerRegistry.objects.get_or_create(
                    symbol=symbol, defaults={"name": name, "is_etf": is_etf}
                )
                created_symbols += int(was_created)
                for alias in _aliases_for(name):
                    # Alias is globally unique; skip if another symbol already owns it.
                    _, a_created = AliasTable.objects.get_or_create(
                        alias=alias, defaults={"symbol": symbol}
                    )
                    created_aliases += int(a_created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(TICKERS)} tickers "
                f"(+{created_symbols} new symbols, +{created_aliases} new aliases)."
            )
        )
