/** Typed HTTP calls to the auth endpoints. */
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import {
  ApiEnvelope,
  AuthMeResponse,
  AuthTokenPair,
  LoginResult,
  MFAEnrollConfirmResponse,
  MFAEnrollResponse,
  Session,
  UserProfile,
} from '../models/auth.models';

const BASE = `${environment.apiBase}/v1`;

// P1-4: requests that set or send the HttpOnly refresh cookie must attach
// credentials so the browser stores the Set-Cookie / replays the cookie
// (required cross-origin; harmless same-origin).
const WITH_COOKIE = { withCredentials: true } as const;

@Injectable({ providedIn: 'root' })
export class AuthApi {
  private http = inject(HttpClient);

  register(email: string, displayName: string, password: string): Observable<ApiEnvelope<{ id: string; email: string }>> {
    return this.http.post<ApiEnvelope<{ id: string; email: string }>>(`${BASE}/auth/register/`, {
      email, display_name: displayName, password,
    });
  }

  verifyEmail(token: string): Observable<ApiEnvelope<AuthTokenPair>> {
    return this.http.post<ApiEnvelope<AuthTokenPair>>(`${BASE}/auth/verify-email/`, { token }, WITH_COOKIE);
  }

  resendVerification(email: string): Observable<ApiEnvelope<{ status: string }>> {
    return this.http.post<ApiEnvelope<{ status: string }>>(`${BASE}/auth/resend-verification/`, { email });
  }

  /**
   * Login. May return either a full token pair OR an MFA challenge — the
   * backend's response shape is discriminated by `mfa_required`.
   */
  login(email: string, password: string): Observable<ApiEnvelope<LoginResult>> {
    return this.http.post<ApiEnvelope<LoginResult>>(`${BASE}/auth/login/`, { email, password }, WITH_COOKIE);
  }

  /** P1-4: no body — the refresh token rides the HttpOnly cookie. */
  refresh(): Observable<ApiEnvelope<AuthTokenPair>> {
    return this.http.post<ApiEnvelope<AuthTokenPair>>(`${BASE}/auth/refresh/`, {}, WITH_COOKIE);
  }

  /** P1-4: no body — the cookie identifies the family; the server clears it. */
  logout(): Observable<ApiEnvelope<{ status: string }>> {
    return this.http.post<ApiEnvelope<{ status: string }>>(`${BASE}/auth/logout/`, {}, WITH_COOKIE);
  }

  passwordReset(email: string): Observable<ApiEnvelope<{ status: string }>> {
    return this.http.post<ApiEnvelope<{ status: string }>>(`${BASE}/auth/password/reset/`, { email });
  }

  passwordResetConfirm(token: string, password: string): Observable<ApiEnvelope<AuthTokenPair>> {
    return this.http.post<ApiEnvelope<AuthTokenPair>>(
      `${BASE}/auth/password/reset/confirm/`, { token, password }, WITH_COOKIE,
    );
  }

  me(): Observable<ApiEnvelope<AuthMeResponse>> {
    return this.http.get<ApiEnvelope<AuthMeResponse>>(`${BASE}/users/me/`);
  }

  // ---- M02 — MFA ----
  mfaEnroll(): Observable<ApiEnvelope<MFAEnrollResponse>> {
    return this.http.post<ApiEnvelope<MFAEnrollResponse>>(`${BASE}/auth/mfa/enroll/`, {});
  }

  mfaEnrollConfirm(code: string): Observable<ApiEnvelope<MFAEnrollConfirmResponse>> {
    return this.http.post<ApiEnvelope<MFAEnrollConfirmResponse>>(
      `${BASE}/auth/mfa/enroll/confirm/`, { code },
    );
  }

  mfaVerify(mfaToken: string, code: string, isBackupCode = false): Observable<ApiEnvelope<AuthTokenPair>> {
    return this.http.post<ApiEnvelope<AuthTokenPair>>(`${BASE}/auth/mfa/verify/`, {
      mfa_token: mfaToken, code, is_backup_code: isBackupCode,
    }, WITH_COOKIE);
  }

  mfaDisable(currentPassword: string, code: string): Observable<ApiEnvelope<{ status: string }>> {
    return this.http.post<ApiEnvelope<{ status: string }>>(`${BASE}/auth/mfa/disable/`, {
      current_password: currentPassword, code,
    });
  }

  mfaRegenerateBackupCodes(currentPassword: string, code: string): Observable<ApiEnvelope<MFAEnrollConfirmResponse>> {
    return this.http.post<ApiEnvelope<MFAEnrollConfirmResponse>>(
      `${BASE}/auth/mfa/backup-codes/regenerate/`, { current_password: currentPassword, code },
    );
  }

  // ---- M02 — profile, sessions, password change ----
  updateProfile(patch: Partial<{ display_name: string; timezone: string; language: string; notification_email: boolean }>): Observable<ApiEnvelope<{ user: AuthMeResponse; profile: UserProfile }>> {
    return this.http.patch<ApiEnvelope<{ user: AuthMeResponse; profile: UserProfile }>>(
      `${BASE}/users/me/update/`, patch,
    );
  }

  changePassword(currentPassword: string, newPassword: string): Observable<ApiEnvelope<{ status: string }>> {
    return this.http.post<ApiEnvelope<{ status: string }>>(`${BASE}/users/me/password/`, {
      current_password: currentPassword, new_password: newPassword,
    });
  }

  listSessions(): Observable<ApiEnvelope<{ sessions: Session[] }>> {
    return this.http.get<ApiEnvelope<{ sessions: Session[] }>>(`${BASE}/users/me/sessions/`);
  }

  revokeSession(familyId: string): Observable<ApiEnvelope<{ revoked: number }>> {
    return this.http.post<ApiEnvelope<{ revoked: number }>>(`${BASE}/users/me/sessions/revoke/`, {
      family_id: familyId,
    });
  }

  revokeAllOtherSessions(): Observable<ApiEnvelope<{ revoked: number }>> {
    return this.http.post<ApiEnvelope<{ revoked: number }>>(`${BASE}/users/me/sessions/revoke/`, {
      all: true,
    });
  }

  // ---- M2.5 — Google OAuth ----
  /** Side-effect-free probe: is Google sign-in configured + enabled here? */
  oauthGoogleAvailable(): Observable<ApiEnvelope<{ enabled: boolean }>> {
    return this.http.get<ApiEnvelope<{ enabled: boolean }>>(`${BASE}/auth/oauth/google/available/`);
  }

  oauthGoogleStart(): Observable<ApiEnvelope<{ authorize_url: string }>> {
    return this.http.get<ApiEnvelope<{ authorize_url: string }>>(`${BASE}/auth/oauth/google/start/`);
  }

  oauthExchange(exchangeCode: string): Observable<ApiEnvelope<LoginResult>> {
    return this.http.post<ApiEnvelope<LoginResult>>(`${BASE}/auth/oauth/exchange/`, {
      exchange: exchangeCode,
    }, WITH_COOKIE);
  }
}
