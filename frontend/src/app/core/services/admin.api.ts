/** Typed HTTP client for the M10 Admin Portal API. All endpoints live under
 *  `/api/v1/admin/` and use the shared `{ data }` / `{ data, meta }` envelope;
 *  the JWT/MFA interceptor handles auth. Staff + MFA is enforced server-side. */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope, ApiError } from '../models/auth.models';
import {
  AdminHealth,
  AdminMeta,
  AdminUserActionBody,
  AdminUserDetail,
  AdminUserListParams,
  AdminUserRow,
  AuditFilters,
  AuditRow,
  DisableResult,
  EnableResult,
  FeatureFlag,
  FlagToggleBody,
  ImpersonationSession,
  ImpersonationStopResult,
  KillswitchBody,
  PlatformStatus,
} from '../models/admin.models';

const BASE = `${environment.apiBase}/v1/admin`;

/** List endpoints (users, audit) carry a `meta` block alongside `data`. */
export interface AdminUsersResponse {
  data: AdminUserRow[];
  meta: AdminMeta;
  error?: ApiError;
}

export interface AuditResponse {
  data: AuditRow[];
  meta: AdminMeta;
  error?: ApiError;
}

@Injectable({ providedIn: 'root' })
export class AdminApi {
  private http = inject(HttpClient);

  // ---- Users ----

  listUsers(params?: AdminUserListParams): Observable<AdminUsersResponse> {
    return this.http.get<AdminUsersResponse>(`${BASE}/users/`, {
      params: this._userParams(params),
    });
  }

  getUser(id: string): Observable<ApiEnvelope<AdminUserDetail>> {
    return this.http.get<ApiEnvelope<AdminUserDetail>>(`${BASE}/users/${id}/`);
  }

  disableUser(id: string, body: AdminUserActionBody): Observable<ApiEnvelope<DisableResult>> {
    return this.http.post<ApiEnvelope<DisableResult>>(`${BASE}/users/${id}/disable/`, body);
  }

  enableUser(id: string, body: AdminUserActionBody): Observable<ApiEnvelope<EnableResult>> {
    return this.http.post<ApiEnvelope<EnableResult>>(`${BASE}/users/${id}/enable/`, body);
  }

  // ---- Impersonation ----

  startImpersonation(id: string, body: AdminUserActionBody): Observable<ApiEnvelope<ImpersonationSession>> {
    return this.http.post<ApiEnvelope<ImpersonationSession>>(
      `${BASE}/users/${id}/impersonate/start/`, body,
    );
  }

  stopImpersonation(sessionId: string): Observable<ApiEnvelope<ImpersonationStopResult>> {
    return this.http.post<ApiEnvelope<ImpersonationStopResult>>(
      `${BASE}/impersonation/${sessionId}/stop/`, {},
    );
  }

  // ---- Audit ----

  listAudit(filters?: AuditFilters): Observable<AuditResponse> {
    return this.http.get<AuditResponse>(`${BASE}/audit/`, {
      params: this._auditParams(filters),
    });
  }

  exportAuditCsv(filters?: AuditFilters): Observable<Blob> {
    return this.http.get(`${BASE}/audit/export.csv`, {
      params: this._auditParams(filters),
      responseType: 'blob',
    });
  }

  // ---- Platform kill switch ----

  platformStatus(): Observable<ApiEnvelope<PlatformStatus>> {
    return this.http.get<ApiEnvelope<PlatformStatus>>(`${BASE}/platform/status/`);
  }

  killswitch(body: KillswitchBody): Observable<ApiEnvelope<PlatformStatus>> {
    return this.http.post<ApiEnvelope<PlatformStatus>>(`${BASE}/platform/killswitch/`, body);
  }

  // ---- Feature flags ----

  listFlags(): Observable<ApiEnvelope<FeatureFlag[]>> {
    return this.http.get<ApiEnvelope<FeatureFlag[]>>(`${BASE}/flags/`);
  }

  toggleFlag(name: string, body: FlagToggleBody): Observable<ApiEnvelope<FeatureFlag>> {
    return this.http.post<ApiEnvelope<FeatureFlag>>(`${BASE}/flags/${name}/`, body);
  }

  // ---- Health ----

  health(): Observable<ApiEnvelope<AdminHealth>> {
    return this.http.get<ApiEnvelope<AdminHealth>>(`${BASE}/health/`);
  }

  // ---- Param builders ----

  private _userParams(params?: AdminUserListParams): HttpParams {
    let p = new HttpParams();
    if (params?.q) { p = p.set('q', params.q); }
    if (params?.is_active !== undefined) { p = p.set('is_active', String(params.is_active)); }
    if (params?.has_broker !== undefined) { p = p.set('has_broker', String(params.has_broker)); }
    if (params?.page) { p = p.set('page', String(params.page)); }
    return p;
  }

  private _auditParams(filters?: AuditFilters): HttpParams {
    let p = new HttpParams();
    if (filters?.user) { p = p.set('user', filters.user); }
    if (filters?.actor) { p = p.set('actor', filters.actor); }
    if (filters?.event_type) { p = p.set('event_type', filters.event_type); }
    if (filters?.entity_type) { p = p.set('entity_type', filters.entity_type); }
    if (filters?.entity_id) { p = p.set('entity_id', filters.entity_id); }
    if (filters?.occurred_after) { p = p.set('occurred_after', filters.occurred_after); }
    if (filters?.occurred_before) { p = p.set('occurred_before', filters.occurred_before); }
    if (filters?.page) { p = p.set('page', String(filters.page)); }
    return p;
  }
}
