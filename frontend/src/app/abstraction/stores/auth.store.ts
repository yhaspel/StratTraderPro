/** Signal-based auth store — single source of truth for auth state. */
import { Injectable, signal, computed } from '@angular/core';
import { AuthUser, AuthStatus, ApiError } from '../../core/models/auth.models';

const REFRESH_KEY = 'stp_refresh_token';

@Injectable({ providedIn: 'root' })
export class AuthStore {
  private readonly _user = signal<AuthUser | null>(null);
  private readonly _accessToken = signal<string | null>(null);
  private readonly _refreshToken = signal<string | null>(this.loadRefresh());
  private readonly _status = signal<AuthStatus>('idle');
  private readonly _error = signal<ApiError | null>(null);
  /**
   * Short-lived MFA challenge token (5 min). Held in memory ONLY — never
   * persisted to localStorage. Survives navigation but not page refresh,
   * which is the right tradeoff for a 5-minute, single-use credential.
   */
  private readonly _mfaToken = signal<string | null>(null);

  // Public readonly signals
  readonly user = this._user.asReadonly();
  readonly accessToken = this._accessToken.asReadonly();
  readonly refreshToken = this._refreshToken.asReadonly();
  readonly status = this._status.asReadonly();
  readonly error = this._error.asReadonly();
  readonly mfaToken = this._mfaToken.asReadonly();
  readonly isAuthenticated = computed(() => this._user() !== null && this._status() === 'authed');
  readonly isMfaPending = computed(() => this._status() === 'mfa_pending' && this._mfaToken() !== null);

  // --- Mutations ---

  setLoading(): void {
    this._status.set('loading');
    this._error.set(null);
  }

  setAuthed(user: AuthUser, access: string, refresh: string): void {
    this._user.set(user);
    this._accessToken.set(access);
    this._refreshToken.set(refresh);
    this._status.set('authed');
    this._error.set(null);
    this._mfaToken.set(null);
    this.persistRefresh(refresh);
  }

  /** Login returned mfa_required — stash the mfa_token and route to /login/mfa. */
  setMfaPending(mfaToken: string): void {
    this._user.set(null);
    this._accessToken.set(null);
    this._refreshToken.set(null);
    this._mfaToken.set(mfaToken);
    this._status.set('mfa_pending');
    this._error.set(null);
    this.removeRefresh();
  }

  /** Patch the user signal in-place (e.g. after /users/me/update/). */
  patchUser(user: Partial<AuthUser>): void {
    const cur = this._user();
    if (cur) {
      this._user.set({ ...cur, ...user });
    }
  }

  setError(error: ApiError): void {
    this._status.set('error');
    this._error.set(error);
  }

  clearError(): void {
    this._error.set(null);
  }

  /**
   * Reset transient form state (status + error) without touching the
   * authenticated user or tokens. Used by /login and /register on init
   * to clear a leftover `'loading'` status from a prior navigation —
   * e.g. user submits register → routes to /resend-verification → uses
   * the back button to /login. Without this, the submit button stays
   * disabled forever because `facade.status() === 'loading'` is still
   * true. No-op if the user is already authed or in MFA challenge so
   * we don't trample real session state.
   */
  setIdle(): void {
    const s = this._status();
    if (s !== 'authed' && s !== 'mfa_pending') {
      this._status.set('idle');
    }
    this._error.set(null);
  }

  clearAuth(): void {
    this._user.set(null);
    this._accessToken.set(null);
    this._refreshToken.set(null);
    this._mfaToken.set(null);
    this._status.set('idle');
    this._error.set(null);
    this.removeRefresh();
  }

  updateTokens(access: string, refresh: string): void {
    this._accessToken.set(access);
    this._refreshToken.set(refresh);
    this.persistRefresh(refresh);
  }

  // --- Storage ---

  private loadRefresh(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(REFRESH_KEY);
  }

  private persistRefresh(token: string): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem(REFRESH_KEY, token);
    }
  }

  private removeRefresh(): void {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(REFRESH_KEY);
    }
  }
}
