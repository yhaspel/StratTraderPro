/** Typed HTTP client for the M04 Brokers API. */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import {
  BrokerAccount,
  BrokerConnectPayload,
  BrokerConnectResult,
  BrokerFlattenResult,
  BrokerStatus,
  BrokerTestConnectionResult,
} from '../models/brokers.models';

const BASE = `${environment.apiBase}/v1/brokers`;

@Injectable({ providedIn: 'root' })
export class BrokersApi {
  private http = inject(HttpClient);

  list(): Observable<ApiEnvelope<BrokerAccount[]>> {
    return this.http.get<ApiEnvelope<BrokerAccount[]>>(`${BASE}/`);
  }

  connect(payload: BrokerConnectPayload): Observable<ApiEnvelope<BrokerConnectResult>> {
    return this.http.post<ApiEnvelope<BrokerConnectResult>>(`${BASE}/`, payload);
  }

  get(id: string): Observable<ApiEnvelope<BrokerAccount>> {
    return this.http.get<ApiEnvelope<BrokerAccount>>(`${BASE}/${id}/`);
  }

  remove(id: string, mfaCode: string): Observable<ApiEnvelope<{ id: string }>> {
    return this.http.request<ApiEnvelope<{ id: string }>>('DELETE', `${BASE}/${id}/`, {
      body: { mfa_code: mfaCode },
    });
  }

  testConnection(id: string): Observable<ApiEnvelope<BrokerTestConnectionResult>> {
    return this.http.post<ApiEnvelope<BrokerTestConnectionResult>>(`${BASE}/${id}/test-connection/`, {});
  }

  status(id: string): Observable<ApiEnvelope<BrokerStatus>> {
    return this.http.get<ApiEnvelope<BrokerStatus>>(`${BASE}/${id}/status/`);
  }

  flatten(id: string): Observable<ApiEnvelope<BrokerFlattenResult>> {
    return this.http.post<ApiEnvelope<BrokerFlattenResult>>(`${BASE}/${id}/flatten/`, {});
  }
}
