/** Typed HTTP client for the M08 Risk API. All responses use the shared
 *  ``{ data }`` envelope; the JWT/MFA interceptor handles auth. */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import {
  KillSwitch,
  RiskEvent,
  RiskEventParams,
  RiskProfile,
  SetKillSwitchBody,
  SizingDecision,
} from '../models/risk.models';

const BASE = `${environment.apiBase}/v1/risk`;

/** POST /risk/killswitches/ returns the created switch (trigger) or a release ack. */
export type SetKillSwitchResult = KillSwitch | { released: boolean };

@Injectable({ providedIn: 'root' })
export class RiskApi {
  private http = inject(HttpClient);

  getProfile(): Observable<ApiEnvelope<RiskProfile>> {
    return this.http.get<ApiEnvelope<RiskProfile>>(`${BASE}/profile/`);
  }

  putProfile(body: Partial<RiskProfile>): Observable<ApiEnvelope<RiskProfile>> {
    return this.http.put<ApiEnvelope<RiskProfile>>(`${BASE}/profile/`, body);
  }

  sizingDecisions(orderId?: string): Observable<ApiEnvelope<SizingDecision[]>> {
    let params = new HttpParams();
    if (orderId) { params = params.set('order_id', orderId); }
    return this.http.get<ApiEnvelope<SizingDecision[]>>(`${BASE}/sizing-decisions/`, { params });
  }

  events(params?: RiskEventParams): Observable<ApiEnvelope<RiskEvent[]>> {
    return this.http.get<ApiEnvelope<RiskEvent[]>>(`${BASE}/events/`, {
      params: this._eventParams(params),
    });
  }

  killswitches(): Observable<ApiEnvelope<KillSwitch[]>> {
    return this.http.get<ApiEnvelope<KillSwitch[]>>(`${BASE}/killswitches/`);
  }

  setKillswitch(body: SetKillSwitchBody): Observable<ApiEnvelope<SetKillSwitchResult>> {
    return this.http.post<ApiEnvelope<SetKillSwitchResult>>(`${BASE}/killswitches/`, body);
  }

  private _eventParams(params?: RiskEventParams): HttpParams {
    let httpParams = new HttpParams();
    if (params?.type) { httpParams = httpParams.set('type', params.type); }
    if (params?.from) { httpParams = httpParams.set('from', params.from); }
    if (params?.to) { httpParams = httpParams.set('to', params.to); }
    return httpParams;
  }
}
