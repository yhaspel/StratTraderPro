/** Profile facade — wraps /api/v1/users/me update + password change. */
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AuthApi } from '../../core/services/auth.api';
import { AuthStore } from '../stores/auth.store';
import { ApiError, AuthMeResponse, UserProfile } from '../../core/models/auth.models';

@Injectable({ providedIn: 'root' })
export class ProfileFacade {
  private api = inject(AuthApi);
  private store = inject(AuthStore);

  // Local signals for the profile screen.
  private readonly _profile = signal<UserProfile | null>(null);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);
  readonly profile = this._profile.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  /** Fetch /users/me/ and refresh both the user signal and the profile signal. */
  async load(): Promise<void> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.me());
      if (res.error) {
        this._error.set(res.error);
        return;
      }
      const me = res.data!;
      this.store.patchUser({
        id: me.id, email: me.email, display_name: me.display_name,
        is_verified: me.is_verified, mfa_enabled: me.mfa_enabled,
      });
      this._profile.set(me.profile);
    } finally {
      this._loading.set(false);
    }
  }

  async update(patch: Partial<{ display_name: string; timezone: string; language: string; notification_email: boolean }>): Promise<boolean> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.updateProfile(patch));
      if (res.error) { this._error.set(res.error); return false; }
      const data = res.data!;
      this.store.patchUser({
        display_name: (data.user as AuthMeResponse).display_name,
        mfa_enabled: (data.user as AuthMeResponse).mfa_enabled,
      });
      this._profile.set(data.profile);
      return true;
    } finally {
      this._loading.set(false);
    }
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<boolean> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.changePassword(currentPassword, newPassword));
      if (res.error) { this._error.set(res.error); return false; }
      return true;
    } finally {
      this._loading.set(false);
    }
  }
}
