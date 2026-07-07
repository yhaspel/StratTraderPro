/** RiskFacade — bridges the RiskApi + RiskStore + UI (M08). */
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import {
  KillSwitchScope,
  RiskEventParams,
  RiskProfile,
} from '../../core/models/risk.models';
import { RiskApi, SetKillSwitchResult } from '../../core/services/risk.api';
import { RiskStore } from '../stores/risk.store';

type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };

/** Options accepted by trigger/release. ``target_id`` scopes a STRATEGY halt. */
export interface HaltOpts {
  target_id?: string;
  reason?: string;
  flatten?: boolean;
  mfa_code?: string;
}

@Injectable({ providedIn: 'root' })
export class RiskFacade {
  private api = inject(RiskApi);
  private store = inject(RiskStore);

  readonly profile = this.store.profile;
  readonly killswitches = this.store.killswitches;
  readonly events = this.store.events;
  readonly sizingDecisions = this.store.sizingDecisions;
  readonly loading = this.store.loading;
  readonly error = this.store.error;
  readonly haltActive = this.store.haltActive;

  async loadProfile(): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.getProfile());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setProfile(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async saveProfile(body: Partial<RiskProfile>): Promise<Result<RiskProfile>> {
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.putProfile(body));
      if (res.error) { return { ok: false, error: res.error }; }
      const value = res.data!;
      this.store.setProfile(value);
      return { ok: true, value };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  async loadKillswitches(): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.killswitches());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setKillswitches(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  async triggerHalt(scope: KillSwitchScope, opts: HaltOpts = {}): Promise<Result<SetKillSwitchResult>> {
    return this._setKillswitch(scope, true, opts);
  }

  async releaseHalt(scope: KillSwitchScope, opts: HaltOpts = {}): Promise<Result<SetKillSwitchResult>> {
    return this._setKillswitch(scope, false, opts);
  }

  async loadEvents(params?: RiskEventParams): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.events(params));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setEvents(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  async loadSizingDecisions(orderId?: string): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.sizingDecisions(orderId));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setSizingDecisions(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  private async _setKillswitch(
    scope: KillSwitchScope,
    active: boolean,
    opts: HaltOpts,
  ): Promise<Result<SetKillSwitchResult>> {
    try {
      const res = await firstValueFrom(this.api.setKillswitch({ scope, active, ...opts }));
      if (res.error) { return { ok: false, error: res.error }; }
      // Refresh the active set so the UI reflects the new state.
      await this.loadKillswitches();
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  private _asError(err: unknown): ApiError {
    const wrapped = err as { appError?: { apiError?: ApiError; message?: string }; message?: string };
    if (wrapped?.appError?.apiError?.code) {
      return wrapped.appError.apiError;
    }
    return {
      code: 'UNKNOWN',
      message: wrapped?.appError?.message ?? wrapped?.message ?? 'Unknown error',
    };
  }
}
