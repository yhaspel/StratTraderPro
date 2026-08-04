/** Typed HTTP calls for terms re-acceptance (M11 §7.8). */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import { TermsAcceptResult, TermsCurrent } from '../models/terms.models';

const BASE = `${environment.apiBase}/v1`;

@Injectable({ providedIn: 'root' })
export class TermsApi {
  private http = inject(HttpClient);

  current(): Observable<ApiEnvelope<TermsCurrent>> {
    return this.http.get<ApiEnvelope<TermsCurrent>>(`${BASE}/terms/current/`);
  }

  accept(tosVersion: string, privacyVersion: string): Observable<ApiEnvelope<TermsAcceptResult>> {
    return this.http.post<ApiEnvelope<TermsAcceptResult>>(`${BASE}/terms/accept/`, {
      tos_version: tosVersion,
      privacy_version: privacyVersion,
    });
  }
}
