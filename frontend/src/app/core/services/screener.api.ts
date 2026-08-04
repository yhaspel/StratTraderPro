/** Typed HTTP client for the strategy screener API (M16 §6.5). */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import {
  ScreenCriteriaResponse,
  ScreenRunCreated,
  ScreenRunDetail,
  ScreenRunSummary,
} from '../models/screener.models';

const base = (strategyId: string) =>
  `${environment.apiBase}/v1/strategies/${strategyId}/screen`;

@Injectable({ providedIn: 'root' })
export class ScreenerApi {
  private http = inject(HttpClient);

  criteria(strategyId: string): Observable<ApiEnvelope<ScreenCriteriaResponse>> {
    return this.http.get<ApiEnvelope<ScreenCriteriaResponse>>(`${base(strategyId)}/criteria/`);
  }

  run(strategyId: string): Observable<ApiEnvelope<ScreenRunCreated>> {
    return this.http.post<ApiEnvelope<ScreenRunCreated>>(`${base(strategyId)}/`, {});
  }

  runs(strategyId: string, limit = 5): Observable<ApiEnvelope<ScreenRunSummary[]>> {
    return this.http.get<ApiEnvelope<ScreenRunSummary[]>>(
      `${base(strategyId)}/runs/?limit=${limit}`,
    );
  }

  run_detail(strategyId: string, runId: string): Observable<ApiEnvelope<ScreenRunDetail>> {
    return this.http.get<ApiEnvelope<ScreenRunDetail>>(`${base(strategyId)}/runs/${runId}/`);
  }
}
