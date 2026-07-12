/** Typed HTTP call for the onboarding checklist (M10.5 §7.3). */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import { OnboardingStatus } from '../models/onboarding.models';

const BASE = `${environment.apiBase}/v1`;

@Injectable({ providedIn: 'root' })
export class OnboardingApi {
  private http = inject(HttpClient);

  getStatus(): Observable<ApiEnvelope<OnboardingStatus>> {
    return this.http.get<ApiEnvelope<OnboardingStatus>>(`${BASE}/onboarding/status/`);
  }
}
