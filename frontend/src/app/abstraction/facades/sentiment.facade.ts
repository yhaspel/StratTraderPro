/** SentimentFacade — bridges the SentimentApi + SentimentStore + UI (M07). */
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import { ArticlesParams, SentimentApi } from '../../core/services/sentiment.api';
import { SentimentStore } from '../stores/sentiment.store';

@Injectable({ providedIn: 'root' })
export class SentimentFacade {
  private api = inject(SentimentApi);
  private store = inject(SentimentStore);

  readonly market = this.store.market;
  readonly articles = this.store.articles;
  readonly symbol = this.store.symbol;
  readonly degraded = this.store.degraded;
  readonly loading = this.store.loading;
  readonly error = this.store.error;

  async loadMarket(): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.market());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setMarket(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async loadArticles(params?: ArticlesParams): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.articles(params));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setArticles(res.data?.articles ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  async loadSymbol(sym: string): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.symbol(sym));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setSymbol(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  private _asError(err: unknown): ApiError {
    const wrapped = err as { appError?: { apiError?: ApiError; message?: string }; message?: string };
    if (wrapped?.appError?.apiError?.code) {
      return wrapped.appError.apiError;
    }
    return {
      code: 'UNKNOWN',
      message: wrapped?.appError?.message ?? wrapped?.message ?? 'Unknown error',
    };
  }
}
