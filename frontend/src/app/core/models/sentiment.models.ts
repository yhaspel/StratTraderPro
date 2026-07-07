/** M07 — News-sentiment domain types. Aligned with the backend sentiment API.
 *  Numeric fields (polarity, impact) are serialized as JSON numbers here (unlike
 *  the Decimal string fields on the orders domain). */

/** A sentiment score for a scope (MARKET, a GICS sector, or a symbol) over a
 *  rolling window. `polarity` is in [-1, +1]; `impact` is an unsigned magnitude. */
export interface SentimentScore {
  scope: string;
  polarity: number;
  impact: number;
  window_minutes: number;
  produced_at: string;
  components: Record<string, number>;
}

/** A scored news article. `polarity`/`label`/`impact` are null until scored. */
export interface SentimentArticle {
  id: string;
  source: string;
  title: string;
  url: string;
  symbols: string[];
  material: boolean;
  published_at: string;
  polarity: number | null;
  label: string | null;
  impact: number | null;
  summary: string;
}

/** GET /sentiment/market/ — market-wide score plus its recent history. */
export interface MarketSentiment {
  current: SentimentScore | null;
  history: SentimentScore[];
  degraded: boolean;
}

/** GET /sentiment/symbol/{sym}/ — per-symbol score plus its recent history. */
export interface SymbolSentiment {
  symbol: string;
  current: SentimentScore | null;
  history: SentimentScore[];
}

/** GET /sentiment/articles/ — a paginated slice of the article feed. */
export interface ArticlesPage {
  articles: SentimentArticle[];
  meta: {
    page: number;
    total: number;
    page_size: number;
  };
}
