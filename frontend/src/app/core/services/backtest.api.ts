/** Typed HTTP client for the M09 Walk-Forward Backtester API. All responses use
 *  the shared ``{ data }`` envelope; the JWT/MFA interceptor handles auth. */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope, ApiError } from '../models/auth.models';
import {
  BacktestMeta,
  BacktestReport,
  BacktestReportFormat,
  BacktestRunDetail,
  BacktestRunListParams,
  BacktestRunRow,
  BacktestStrategyOption,
  CreateBacktestRunBody,
} from '../models/backtest.models';

const BASE = `${environment.apiBase}/v1/backtest`;

/** GET /backtest/runs/ carries a page ``meta`` block alongside ``data``. */
export interface BacktestRunsResponse {
  data: BacktestRunRow[];
  meta: BacktestMeta;
  error?: ApiError;
}

@Injectable({ providedIn: 'root' })
export class BacktestApi {
  private http = inject(HttpClient);

  strategies(): Observable<ApiEnvelope<BacktestStrategyOption[]>> {
    return this.http.get<ApiEnvelope<BacktestStrategyOption[]>>(`${BASE}/strategies/`);
  }

  createRun(body: CreateBacktestRunBody): Observable<ApiEnvelope<BacktestRunDetail>> {
    return this.http.post<ApiEnvelope<BacktestRunDetail>>(`${BASE}/runs/`, body);
  }

  listRuns(params?: BacktestRunListParams): Observable<BacktestRunsResponse> {
    return this.http.get<BacktestRunsResponse>(`${BASE}/runs/`, {
      params: this._filterParams(params),
    });
  }

  getRun(id: string): Observable<ApiEnvelope<BacktestRunDetail>> {
    return this.http.get<ApiEnvelope<BacktestRunDetail>>(`${BASE}/runs/${id}/`);
  }

  cancelRun(id: string): Observable<ApiEnvelope<{ id: string; status: string }>> {
    return this.http.post<ApiEnvelope<{ id: string; status: string }>>(
      `${BASE}/runs/${id}/cancel/`, {},
    );
  }

  /** Parsed report JSON for the charts (content-disposition is ignored by XHR). */
  reportJson(id: string): Observable<BacktestReport> {
    return this.http.get<BacktestReport>(`${BASE}/runs/${id}/report.json`);
  }

  /** Raw artifact bytes for the download buttons (blob pattern). */
  reportBlob(id: string, fmt: BacktestReportFormat): Observable<Blob> {
    return this.http.get(`${BASE}/runs/${id}/report.${fmt}`, { responseType: 'blob' });
  }

  private _filterParams(params?: BacktestRunListParams): HttpParams {
    let httpParams = new HttpParams();
    if (params?.status) { httpParams = httpParams.set('status', params.status); }
    if (params?.from) { httpParams = httpParams.set('from', params.from); }
    if (params?.to) { httpParams = httpParams.set('to', params.to); }
    if (params?.page) { httpParams = httpParams.set('page', String(params.page)); }
    return httpParams;
  }
}
