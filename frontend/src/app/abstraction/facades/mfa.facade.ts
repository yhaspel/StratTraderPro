/** MFA enrollment / disable facade. */
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AuthApi } from '../../core/services/auth.api';
import { AuthStore } from '../stores/auth.store';
import { ApiError, MFAEnrollResponse } from '../../core/models/auth.models';

@Injectable({ providedIn: 'root' })
export class MfaFacade {
  private api = inject(AuthApi);
  private store = inject(AuthStore);

  private readonly _enroll = signal<MFAEnrollResponse | null>(null);
  private readonly _backupCodes = signal<string[] | null>(null);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly enroll = this._enroll.asReadonly();
  readonly backupCodes = this._backupCodes.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  async beginEnroll(): Promise<boolean> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.mfaEnroll());
      if (res.error) { this._error.set(res.error); return false; }
      this._enroll.set(res.data!);
      return true;
    } finally {
      this._loading.set(false);
    }
  }

  async confirmEnroll(code: string): Promise<boolean> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.mfaEnrollConfirm(code));
      if (res.error) { this._error.set(res.error); return false; }
      this._backupCodes.set(res.data!.backup_codes);
      this.store.patchUser({ mfa_enabled: true });
      return true;
    } finally {
      this._loading.set(false);
    }
  }

  async disable(currentPassword: string, code: string): Promise<boolean> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.mfaDisable(currentPassword, code));
      if (res.error) { this._error.set(res.error); return false; }
      this.store.patchUser({ mfa_enabled: false });
      this._backupCodes.set(null);
      this._enroll.set(null);
      return true;
    } finally {
      this._loading.set(false);
    }
  }

  async regenerateBackupCodes(currentPassword: string, code: string): Promise<boolean> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.mfaRegenerateBackupCodes(currentPassword, code));
      if (res.error) { this._error.set(res.error); return false; }
      this._backupCodes.set(res.data!.backup_codes);
      return true;
    } finally {
      this._loading.set(false);
    }
  }

  reset(): void {
    this._enroll.set(null);
    this._backupCodes.set(null);
    this._error.set(null);
  }
}
