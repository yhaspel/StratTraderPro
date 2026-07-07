/** Signal-based store for the M07 news sentiment.
 *
 * Holds the latest market sentiment (current score + recent history), the
 * degraded flag, the article feed, the optional per-symbol sentiment, plus
 * loading/error flags. */
import { Injectable, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import {
  MarketSentiment,
  SentimentArticle,
  SymbolSentiment,
} from '../../core/models/sentiment.models';

@Injectable({ providedIn: 'root' })
export class SentimentStore {
  private readonly _market = signal<MarketSentiment | null>(null);
  private readonly _articles = signal<SentimentArticle[]>([]);
  private readonly _symbol = signal<SymbolSentiment | null>(null);
  private readonly _degraded = signal(false);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly market = this._market.asReadonly();
  readonly articles = this._articles.asReadonly();
  readonly symbol = this._symbol.asReadonly();
  readonly degraded = this._degraded.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  setMarket(market: MarketSentiment | null) {
    this._market.set(market);
    this._degraded.set(market?.degraded ?? false);
  }
  setArticles(articles: SentimentArticle[]) { this._articles.set(articles); }
  setSymbol(symbol: SymbolSentiment | null) { this._symbol.set(symbol); }
  setLoading(loading: boolean) { this._loading.set(loading); }
  setError(err: ApiError | null) { this._error.set(err); }

  reset() {
    this._market.set(null);
    this._articles.set([]);
    this._symbol.set(null);
    this._degraded.set(false);
    this._error.set(null);
  }
}
