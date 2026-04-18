/** Typed HTTP calls to the auth endpoints. */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope, AuthTokenPair, AuthUser } from '../models/auth.models';

const BASE = `${environment.apiBase}/v1`;

@Injectable({ providedIn: 'root' })
export class AuthApi {
  private http = inject(HttpClient);

  register(email: string, displayName: string, password: string): Observable<ApiEnvelope<{ id: string; email: string }>> {
    return this.http.post<ApiEnvelope<{ id: string; email: string }>>(`${BASE}/auth/register/`, {
      email, display_name: displayName, password,
    });
  }

  verifyEmail(token: string): Observable<ApiEnvelope<AuthTokenPair>> {
    return this.http.post<ApiEnvelope<AuthTokenPair>>(`${BASE}/auth/verify-email/`, { token });
  }

  resendVerification(email: string): Observable<ApiEnvelope<{ status: string }>> {
    return this.http.post<ApiEnvelope<{ status: string }>>(`${BASE}/auth/resend-verification/`, { email });
  }

  login(email: string, password: string): Observable<ApiEnvelope<AuthTokenPair>> {
    return this.http.post<ApiEnvelope<AuthTokenPair>>(`${BASE}/auth/login/`, { email, password });
  }

  refresh(refreshToken: string): Observable<ApiEnvelope<AuthTokenPair>> {
    return this.http.post<ApiEnvelope<AuthTokenPair>>(`${BASE}/auth/refresh/`, { refresh: refreshToken });
  }

  logout(refreshToken: string): Observable<ApiEnvelope<{ status: string }>> {
    return this.http.post<ApiEnvelope<{ status: string }>>(`${BASE}/auth/logout/`, { refresh: refreshToken });
  }

  passwordReset(email: string): Observable<ApiEnvelope<{ status: string }>> {
    return this.http.post<ApiEnvelope<{ status: string }>>(`${BASE}/auth/password/reset/`, { email });
  }

  passwordResetConfirm(token: string, password: string): Observable<ApiEnvelope<AuthTokenPair>> {
    return this.http.post<ApiEnvelope<AuthTokenPair>>(`${BASE}/auth/password/reset/confirm/`, { token, password });
  }

  me(): Observable<ApiEnvelope<AuthUser>> {
    return this.http.get<ApiEnvelope<AuthUser>>(`${BASE}/users/me/`);
  }
}
