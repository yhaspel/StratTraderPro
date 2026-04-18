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

  // Public readonly signals
  readonly user = this._user.asReadonly();
  readonly accessToken = this._accessToken.asReadonly();
  readonly refreshToken = this._refreshToken.asReadonly();
  readonly status = this._status.asReadonly();
  readonly error = this._error.asReadonly();
  readonly isAuthenticated = computed(() => this._user() !== null && this._status() === 'authed');

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
    this.persistRefresh(refresh);
  }

  setError(error: ApiError): void {
    this._status.set('error');
    this._error.set(error);
  }

  clearAuth(): void {
    this._user.set(null);
    this._accessToken.set(null);
    this._refreshToken.set(null);
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
