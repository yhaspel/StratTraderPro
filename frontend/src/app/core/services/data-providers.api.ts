/** Typed HTTP client for the marketdata data-provider keys API (ADR-062). */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import { DataProvider, DataProviderKeys } from '../models/data-providers.models';

const BASE = `${environment.apiBase}/v1/marketdata/keys`;

@Injectable({ providedIn: 'root' })
export class DataProvidersApi {
  private http = inject(HttpClient);

  status(): Observable<ApiEnvelope<DataProviderKeys>> {
    return this.http.get<ApiEnvelope<DataProviderKeys>>(`${BASE}/`);
  }

  /** Write-only: the key goes up, never comes back. */
  set(provider: DataProvider, apiKey: string): Observable<ApiEnvelope<DataProviderKeys>> {
    return this.http.put<ApiEnvelope<DataProviderKeys>>(`${BASE}/${provider.toLowerCase()}/`, {
      api_key: apiKey,
    });
  }

  remove(provider: DataProvider): Observable<ApiEnvelope<DataProviderKeys>> {
    return this.http.delete<ApiEnvelope<DataProviderKeys>>(`${BASE}/${provider.toLowerCase()}/`);
  }
}
