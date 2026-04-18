/** Auth facade — orchestrates API calls, store updates, and navigation. */
import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { AuthApi } from '../../core/services/auth.api';
import { AuthStore } from '../stores/auth.store';
import { ApiError, AuthTokenPair } from '../../core/models/auth.models';

@Injectable({ providedIn: 'root' })
export class AuthFacade {
  private api = inject(AuthApi);
  private store = inject(AuthStore);
  private router = inject(Router);

  // Expose store signals for templates
  readonly user = this.store.user;
  readonly status = this.store.status;
  readonly error = this.store.error;
  readonly isAuthenticated = this.store.isAuthenticated;

  async register(email: string, displayName: string, password: string): Promise<boolean> {
    this.store.setLoading();
    try {
      const res = await firstValueFrom(this.api.register(email, displayName, password));
      if (res.error) { this.store.setError(res.error); return false; }
      await this.router.navigate(['/resend-verification'], { queryParams: { email } });
      return true;
    } catch (e) {
      this.handleError(e);
      return false;
    }
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
      this.applyTokenPair(res.data!);
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
