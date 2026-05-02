/** Sessions facade — list and revoke active refresh-token families. */
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AuthApi } from '../../core/services/auth.api';
import { ApiError, Session } from '../../core/models/auth.models';

@Injectable({ providedIn: 'root' })
export class SessionsFacade {
  private api = inject(AuthApi);

  private readonly _sessions = signal<Session[]>([]);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly sessions = this._sessions.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  async load(): Promise<void> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.listSessions());
      if (res.error) { this._error.set(res.error); return; }
      this._sessions.set(res.data!.sessions);
    } finally {
      this._loading.set(false);
    }
  }

  async revoke(familyId: string): Promise<boolean> {
    const res = await firstValueFrom(this.api.revokeSession(familyId));
    if (res.error) { this._error.set(res.error); return false; }
    await this.load();
    return true;
  }

  async revokeAllOthers(): Promise<boolean> {
    const res = await firstValueFrom(this.api.revokeAllOtherSessions());
    if (res.error) { this._error.set(res.error); return false; }
    await this.load();
    return true;
  }
}
