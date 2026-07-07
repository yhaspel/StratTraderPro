/** Typed HTTP client for the M07 Sentiment API. All responses use the shared
 *  ``{ data }`` envelope; the JWT interceptor handles auth (MFA-enforced). */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import { ArticlesPage, MarketSentiment, SymbolSentiment } from '../models/sentiment.models';

const BASE = `${environment.apiBase}/v1`;

/** Optional filters for GET /sentiment/articles/. */
export interface ArticlesParams {
  symbol?: string;
  from?: string;
  to?: string;
  page?: number;
}

@Injectable({ providedIn: 'root' })
export class SentimentApi {
  private http = inject(HttpClient);

  market(): Observable<ApiEnvelope<MarketSentiment>> {
    return this.http.get<ApiEnvelope<MarketSentiment>>(`${BASE}/sentiment/market/`);
  }

  symbol(sym: string): Observable<ApiEnvelope<SymbolSentiment>> {
    return this.http.get<ApiEnvelope<SymbolSentiment>>(`${BASE}/sentiment/symbol/${sym}/`);
  }

  articles(params?: ArticlesParams): Observable<ApiEnvelope<ArticlesPage>> {
    return this.http.get<ApiEnvelope<ArticlesPage>>(`${BASE}/sentiment/articles/`, {
      params: this._filterParams(params),
    });
  }

  private _filterParams(params?: ArticlesParams): HttpParams {
    let httpParams = new HttpParams();
    if (params?.symbol) { httpParams = httpParams.set('symbol', params.symbol); }
    if (params?.from) { httpParams = httpParams.set('from', params.from); }
    if (params?.to) { httpParams = httpParams.set('to', params.to); }
    if (params?.page != null) { httpParams = httpParams.set('page', String(params.page)); }
    return httpParams;
  }
}
