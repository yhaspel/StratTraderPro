/** Typed HTTP client for the M06 Regime API. All responses use the shared
 *  ``{ data }`` envelope; the JWT interceptor handles auth (MFA-enforced). */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import { RegimeModelInfo, RegimeObservation } from '../models/regime.models';

const BASE = `${environment.apiBase}/v1`;

/** Optional filters for GET /regime/history/. */
export interface RegimeHistoryParams {
  scope?: string;
  from?: string;
  to?: string;
}

@Injectable({ providedIn: 'root' })
export class RegimeApi {
  private http = inject(HttpClient);

  current(): Observable<ApiEnvelope<RegimeObservation | null>> {
    return this.http.get<ApiEnvelope<RegimeObservation | null>>(`${BASE}/regime/current/`);
  }

  history(params?: RegimeHistoryParams): Observable<ApiEnvelope<RegimeObservation[]>> {
    return this.http.get<ApiEnvelope<RegimeObservation[]>>(`${BASE}/regime/history/`, {
      params: this._filterParams(params),
    });
  }

  model(): Observable<ApiEnvelope<RegimeModelInfo>> {
    return this.http.get<ApiEnvelope<RegimeModelInfo>>(`${BASE}/regime/model/`);
  }

  private _filterParams(params?: RegimeHistoryParams): HttpParams {
    let httpParams = new HttpParams();
    if (params?.scope) { httpParams = httpParams.set('scope', params.scope); }
    if (params?.from) { httpParams = httpParams.set('from', params.from); }
    if (params?.to) { httpParams = httpParams.set('to', params.to); }
    return httpParams;
  }
}
