/** Typed HTTP client for the M03 Strategies API. */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import {
  Strategy,
  StrategyUploadPayload,
  WebhookConfig,
  WebhookDryRunResult,
  WebhookRotateResponse,
} from '../models/strategies.models';

const BASE = `${environment.apiBase}/v1/strategies`;

@Injectable({ providedIn: 'root' })
export class StrategiesApi {
  private http = inject(HttpClient);

  list(): Observable<ApiEnvelope<Strategy[]>> {
    return this.http.get<ApiEnvelope<Strategy[]>>(`${BASE}/`);
  }

  get(id: string): Observable<ApiEnvelope<Strategy>> {
    return this.http.get<ApiEnvelope<Strategy>>(`${BASE}/${id}/`);
  }

  upload(payload: StrategyUploadPayload): Observable<ApiEnvelope<Strategy>> {
    const fd = new FormData();
    fd.append('pine', payload.pine);
    fd.append('description', payload.description);
    fd.append('webhook', payload.webhook);
    fd.append('accept_untested_risk', String(payload.acceptUntestedRisk));
    return this.http.post<ApiEnvelope<Strategy>>(`${BASE}/`, fd);
  }

  patch(id: string, body: Partial<{ name: string; is_enabled: boolean }>): Observable<ApiEnvelope<Strategy>> {
    return this.http.patch<ApiEnvelope<Strategy>>(`${BASE}/${id}/`, body);
  }

  delete(id: string): Observable<ApiEnvelope<{ id: string; is_enabled: false }>> {
    return this.http.delete<ApiEnvelope<{ id: string; is_enabled: false }>>(`${BASE}/${id}/`);
  }

  download(id: string, kind: 'PINE' | 'DESC' | 'WEBHOOK_TEMPLATE'): Observable<Blob> {
    return this.http.get(`${BASE}/${id}/files/${kind}/`, { responseType: 'blob' });
  }

  getWebhookConfig(id: string): Observable<ApiEnvelope<WebhookConfig>> {
    return this.http.get<ApiEnvelope<WebhookConfig>>(`${BASE}/${id}/webhook-config/`);
  }

  putWebhookConfig(id: string, body: { json_schema: unknown; payload_template: unknown }): Observable<ApiEnvelope<WebhookConfig>> {
    return this.http.put<ApiEnvelope<WebhookConfig>>(`${BASE}/${id}/webhook-config/`, body);
  }

  rotateWebhookSecret(id: string): Observable<ApiEnvelope<WebhookRotateResponse>> {
    return this.http.post<ApiEnvelope<WebhookRotateResponse>>(`${BASE}/${id}/webhook-config/rotate/`, {});
  }

  dryRunWebhook(id: string, payload: unknown): Observable<ApiEnvelope<WebhookDryRunResult>> {
    return this.http.post<ApiEnvelope<WebhookDryRunResult>>(`${BASE}/${id}/webhook-config/dry-run/`, { payload });
  }
}
