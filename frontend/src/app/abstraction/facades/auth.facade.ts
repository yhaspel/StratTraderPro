/** Auth facade — orchestrates API calls, store updates, and navigation. */
import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { AuthApi } from '../../core/services/auth.api';
import { AuthStore } from '../stores/auth.store';
import { ApiError, AuthTokenPair, LoginResult } from '../../core/models/auth.models';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class AuthFacade {
  private api = inject(AuthApi);
  private store = inject(AuthStore);
  private router = inject(Router);

  // Expose store signals for templates
  readonly user = this.store.user;
  readonly status = this.store.status;
  readonly error = this.store.error;
  readonly mfaToken = this.store.mfaToken;
  readonly isAuthenticated = this.store.isAuthenticated;
  readonly isMfaPending = this.store.isMfaPending;

  async register(email: string, displayName: string, password: string): Promise<boolean> {
    this.store.setLoading();
    try {
      const res = await firstValueFrom(this.api.register(email, displayName, password));
      if (res.error) { this.store.setError(res.error); return false; }
      // Reset status before navigating away — register doesn't authenticate
      // the user (they still need to verify their email and then sign in),
      // so leaving status='loading' would freeze the /login submit button
      // when they come back to it.
      this.store.setIdle();
      await this.router.navigate(['/resend-verification'], { queryParams: { email } });
      return true;
    } catch (e) {
      this.handleError(e);
      return false;
    }
  }

  /**
   * Clear any stale `'loading'` status left behind by a prior navigation
   * (e.g. register → /resend-verification → back to /login). Called by
   * the login screen on init so the submit button isn't stuck disabled.
   * No-op when the user is already authed or in MFA challenge.
   */
  resetFormState(): void {
    this.store.setIdle();
  }

  async verifyEmail(token: string): Promise<boolean> {
    this.store.setLoading();
    try {
      const res = await firstValueFrom(this.api.verifyEmail(token));
      if (res.error) { this.store.setError(res.error); return false; }
      this.applyTokenPair(res.data!);
      await this.router.navigate(['/dashboard']);
      return true;
    } catch (e) {
      this.handleError(e);
      return false;
    }
  }

  async resendVerification(email: string): Promise<boolean> {
    try {
      await firstValueFrom(this.api.resendVerification(email));
      return true;
    } catch {
      return false;
    }
  }

  async login(email: string, password: string): Promise<boolean> {
    this.store.setLoading();
    try {
      const res = await firstValueFrom(this.api.login(email, password));
      if (res.error) { this.store.setError(res.error); return false; }
      const data = res.data!;
      // Discriminated union: mfa_required=true means we got an mfa_token
      // instead of a token pair.
      if ((data as LoginResult).mfa_required === true) {
        const mfaToken = (data as { mfa_token: string }).mfa_token;
        this.store.setMfaPending(mfaToken);
        await this.router.navigate(['/login/mfa']);
        return true;
      }
      this.applyTokenPair(data as AuthTokenPair);
      const next = this.router.parseUrl(this.router.url).queryParams['next'] || '/dashboard';
      await this.router.navigateByUrl(next as string);
      return true;
    } catch (e) {
      this.handleError(e);
      return false;
    }
  }

  /** Submit a TOTP or backup code paired with the held mfa_token. */
  async verifyMfa(code: string, isBackupCode = false): Promise<boolean> {
    const token = this.store.mfaToken();
    if (!token) {
      this.store.setError({ code: 'MFA_TOKEN_MISSING', message: 'Session expired. Sign in again.' });
      await this.router.navigate(['/login']);
      return false;
    }
    this.store.setLoading();
    try {
      const res = await firstValueFrom(this.api.mfaVerify(token, code, isBackupCode));
      if (res.error) {
        this.store.setError(res.error);
        // Restore mfa_pending state so the user can retry without re-login.
        this.store.setMfaPending(token);
        return false;
      }
      this.applyTokenPair(res.data!);
      const next = this.router.parseUrl(this.router.url).queryParams['next'] || '/dashboard';
      await this.router.navigateByUrl(next as string);
      return true;
    } catch (e) {
      this.handleError(e);
      return false;
    }
  }

  /** Abandon the MFA-pending state and bounce back to /login. */
  async cancelMfa(): Promise<void> {
    this.store.clearAuth();
    await this.router.navigate(['/login']);
  }

  // -------------------------------------------------------------------------
  // M2.5 — Google OAuth
  // -------------------------------------------------------------------------
  /**
   * Kick off Google sign-in.
   *
   * The user must navigate to the BACKEND'S ABSOLUTE URL (not the same-origin
   * `/api/` proxy on the frontend host) — otherwise the Django session cookie
   * set during /start/ would be attached to the frontend's domain, and the
   * browser would drop it when Google redirects to the backend's domain at
   * the end of the OAuth round-trip. The cookie domain is what makes
   * allauth's state-verification work.
   *
   * The absolute backend URL is exposed at runtime via `window.STP_CONFIG`,
   * which nginx fills in from the BACKEND_URL env var (see
   * docker/nginx.conf.template). Falls back to the same-origin /api proxy
   * for local dev where there's no nginx; in that case the OAuth flow won't
   * cross domains anyway.
   */
  async startGoogleSignIn(): Promise<void> {
    this.store.setLoading();
    const backendUrl = (window as unknown as { STP_CONFIG?: { backendUrl?: string } }).STP_CONFIG?.backendUrl;
    const target = backendUrl
      ? `${backendUrl.replace(/\/$/, '')}/api/v1/auth/oauth/google/start/`
      : `${environment.apiBase}/v1/auth/oauth/google/start/`;
    window.location.assign(target);
  }

  /**
   * Called by the /oauth/callback route component when the browser lands
   * back from Google. Swaps the exchange code for tokens (or routes to MFA).
   */
  async completeGoogleSignIn(exchangeCode: string): Promise<boolean> {
    this.store.setLoading();
    try {
      const res = await firstValueFrom(this.api.oauthExchange(exchangeCode));
      if (res.error) { this.store.setError(res.error); return false; }
      const data = res.data!;
      if ((data as LoginResult).mfa_required === true) {
        const mfaToken = (data as { mfa_token: string }).mfa_token;
        this.store.setMfaPending(mfaToken);
        await this.router.navigate(['/login/mfa']);
        return true;
      }
      this.applyTokenPair(data as AuthTokenPair);
      const next = this.router.parseUrl(this.router.url).queryParams['next'] || '/dashboard';
      await this.router.navigateByUrl(next as string);
      return true;
    } catch (e) {
      this.handleError(e);
      return false;
    }
  }

  async logout(): Promise<void> {
    const refresh = this.store.refreshToken();
    if (refresh) {
      try { await firstValueFrom(this.api.logout(refresh)); } catch { /* best effort */ }
    }
    this.store.clearAuth();
    await this.router.navigate(['/login']);
  }

  async refreshSession(): Promise<boolean> {
    const refresh = this.store.refreshToken();
    if (!refresh) return false;
    try {
      const res = await firstValueFrom(this.api.refresh(refresh));
      if (res.error) { this.store.clearAuth(); return false; }
      this.applyTokenPair(res.data!);
      return true;
    } catch {
      this.store.clearAuth();
      return false;
    }
  }

  async passwordReset(email: string): Promise<boolean> {
    try {
      await firstValueFrom(this.api.passwordReset(email));
      return true;
    } catch {
      return false;
    }
  }

  async passwordResetConfirm(token: string, password: string): Promise<boolean> {
    this.store.setLoading();
    try {
      const res = await firstValueFrom(this.api.passwordResetConfirm(token, password));
      if (res.error) { this.store.setError(res.error); return false; }
      this.applyTokenPair(res.data!);
      await this.router.navigate(['/dashboard']);
      return true;
    } catch (e) {
      this.handleError(e);
      return false;
    }
  }

  /** Attempt silent refresh on app bootstrap. */
  async initSession(): Promise<void> {
    if (this.store.refreshToken()) {
      await this.refreshSession();
    }
  }

  // --- Private ---

  private applyTokenPair(pair: AuthTokenPair): void {
    this.store.setAuthed(pair.user, pair.access, pair.refresh);
  }

  private handleError(e: unknown): void {
    const err = (e as { error?: { error?: ApiError } })?.error?.error;
    if (err) {
      this.store.setError(err);
    } else {
      this.store.setError({ code: 'UNKNOWN', message: 'An unexpected error occurred.' });
    }
  }
}
