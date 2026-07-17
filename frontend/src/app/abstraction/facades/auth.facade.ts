/** Auth facade — orchestrates API calls, store updates, and navigation. */
import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { AuthApi } from '../../core/services/auth.api';
import { AuthStore } from '../stores/auth.store';
import { ApiError, AuthTokenPair, LoginResult } from '../../core/models/auth.models';
import { environment } from '../../../environments/environment';
import { DashboardWsService } from '../../core/services/ws.service';

/** P2-14 — bootstrap silent-refresh timeout; the app boots unauthenticated past this. */
const INIT_REFRESH_TIMEOUT_MS = 8_000;

@Injectable({ providedIn: 'root' })
export class AuthFacade {
  private api = inject(AuthApi);
  private store = inject(AuthStore);
  private router = inject(Router);
  private ws = inject(DashboardWsService);

  // Expose store signals for templates
  readonly user = this.store.user;
  readonly status = this.store.status;
  readonly error = this.store.error;
  readonly mfaToken = this.store.mfaToken;
  readonly isAuthenticated = this.store.isAuthenticated;
  readonly isMfaPending = this.store.isMfaPending;

  // Whether Google sign-in is configured + enabled in THIS deploy. Starts null
  // ("unknown"); the Google button stays hidden until confirmed true, so an
  // unconfigured deploy never shows a button that dead-ends on 503 (§Google fix).
  private readonly _googleAvailable = signal<boolean | null>(null);
  readonly googleAvailable = this._googleAvailable.asReadonly();
  private googleProbe: Promise<void> | null = null;

  /**
   * Probe the backend once for Google-OAuth availability.
   *
   * BUG: the first version cached `false` on ANY thrown error. A 502 from the
   * platform while the backend was redeploying is not an answer — but it was
   * being treated as one, so "Continue with Google" silently vanished from
   * /login and /register for the whole session, and only came back on a reload
   * that happened to land after the backend was up. That is the "Google sign-in
   * is missing" report; reproduced live (502 -> no button, 200 -> button).
   *
   * So: only a RESPONSE from the backend is an answer.
   *   - 2xx            -> trust `data.enabled` (true shows the button, false hides it).
   *   - 4xx            -> the backend spoke and refused: the feature is off. Hide.
   *   - 5xx / 0 / net  -> nobody answered. Retry briefly, and if we still have
   *                       nothing, leave the state `null` (unknown) so the NEXT
   *                       mount re-probes instead of caching a lie forever.
   *
   * Concurrent callers (login + register both mount the button) share one probe.
   */
  async loadGoogleAvailability(): Promise<void> {
    if (this._googleAvailable() !== null) { return; }
    if (this.googleProbe) { return this.googleProbe; }
    this.googleProbe = this.probeGoogle().finally(() => { this.googleProbe = null; });
    return this.googleProbe;
  }

  private async probeGoogle(): Promise<void> {
    const backoffMs = [300, 900];   // 3 attempts total; ~1.2s worst case
    for (let attempt = 0; ; attempt++) {
      try {
        const res = await firstValueFrom(this.api.oauthGoogleAvailable());
        this._googleAvailable.set(!!res.data?.enabled);
        return;
      } catch (err: unknown) {
        const status = (err as { status?: number })?.status ?? 0;
        if (status >= 400 && status < 500) {
          this._googleAvailable.set(false);  // a real "no" from the backend
          return;
        }
        if (attempt >= backoffMs.length) {
          return;  // still unknown — stay null so a later mount tries again
        }
        await new Promise((r) => setTimeout(r, backoffMs[attempt]));
      }
    }
  }

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
      await this.router.navigateByUrl(this.safeNext());
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
      await this.router.navigateByUrl(this.safeNext());
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
      await this.router.navigateByUrl(this.safeNext());
      return true;
    } catch (e) {
      this.handleError(e);
      return false;
    }
  }

  async logout(): Promise<void> {
    // P2-11: tear the dashboard socket down (this is the path the refresh
    // interceptor calls on auth failure) so it doesn't reconnect on a dead session.
    this.ws.forceDisconnect();
    // P1-4: the refresh token rides the HttpOnly cookie; logout() sends no body
    // and the server revokes the family + clears the cookie.
    try { await firstValueFrom(this.api.logout()); } catch { /* best effort */ }
    this.store.clearAuth();
    await this.router.navigate(['/login']);
  }

  /** M10.5 §7.1/AC-10.5-3 — user-initiated sign-out from the shell user menu:
   * tears down the shared dashboard WebSocket (C-FE-4), revokes on the server
   * (best-effort), clears auth state, and lands on the public landing ("/"). */
  async signOut(): Promise<void> {
    this.ws.forceDisconnect();
    try { await firstValueFrom(this.api.logout()); } catch { /* best effort */ }
    this.store.clearAuth();
    await this.router.navigate(['/']);
  }

  async refreshSession(): Promise<boolean> {
    // P1-4: the refresh token is an HttpOnly cookie the SPA can't read, so we
    // always attempt a rotation; the server 401s (and we clear) if there's none.
    try {
      const res = await firstValueFrom(this.api.refresh());
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
    // P1-4: we can't read the HttpOnly cookie from JS, so always try a refresh;
    // it resolves to authed if a valid session cookie exists, else clears.
    // P2-14: cap it so a slow/hung backend can't white-screen first paint — the
    // app boots unauthenticated and recovers when the refresh eventually settles.
    await Promise.race([
      this.refreshSession(),
      new Promise<void>((resolve) => setTimeout(resolve, INIT_REFRESH_TIMEOUT_MS)),
    ]);
  }

  // --- Private ---

  /** P3-7 — a post-login `next` is honoured only if it is a same-origin absolute
   * path: exactly one leading '/', never '//' (protocol-relative) or 'scheme:'. */
  private safeNext(): string {
    const raw = this.router.parseUrl(this.router.url).queryParams['next'];
    return typeof raw === 'string' && /^\/(?!\/)/.test(raw) ? raw : '/dashboard';
  }

  private applyTokenPair(pair: AuthTokenPair): void {
    this.store.setAuthed(pair.user, pair.access);
  }

  private handleError(e: unknown): void {
    // C-FE-3: read the standardized `appError` envelope the errorInterceptor
    // attaches (same convention as every other facade), not the raw
    // `e.error.error`. Falls back to UNKNOWN, which has an en.json key.
    const err = (e as { appError?: { apiError?: ApiError } })?.appError?.apiError;
    if (err?.code) {
      this.store.setError(err);
    } else {
      this.store.setError({ code: 'UNKNOWN', message: 'An unexpected error occurred.' });
    }
  }
}
