/** BrokersFacade — bridges the BrokersApi + BrokersStore + UI. */
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import {
  BrokerConnectPayload,
  BrokerConnectResult,
  BrokerFlattenResult,
  BrokerTestConnectionResult,
} from '../../core/models/brokers.models';
import { BrokersApi } from '../../core/services/brokers.api';
import { BrokersStore } from '../stores/brokers.store';

type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };

@Injectable({ providedIn: 'root' })
export class BrokersFacade {
  private api = inject(BrokersApi);
  private store = inject(BrokersStore);

  readonly accounts = this.store.accounts;
  readonly loading = this.store.loading;
  readonly error = this.store.error;

  async load(): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.list());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setAccounts(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async connect(payload: BrokerConnectPayload): Promise<Result<BrokerConnectResult>> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.connect(payload));
      if (res.error) { this.store.setError(res.error); return { ok: false, error: res.error }; }
      const value = res.data!;
      this.store.upsertAccount(value);
      return { ok: true, value };
    } catch (err) {
      const e = this._asError(err);
      this.store.setError(e);
      return { ok: false, error: e };
    } finally {
      this.store.setLoading(false);
    }
  }

  async testConnection(id: string): Promise<Result<BrokerTestConnectionResult>> {
    try {
      const res = await firstValueFrom(this.api.testConnection(id));
      if (res.error) { return { ok: false, error: res.error }; }
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  async remove(id: string, mfaCode: string): Promise<{ ok: boolean; error?: ApiError }> {
    try {
      const res = await firstValueFrom(this.api.remove(id, mfaCode));
      if (res?.error) { return { ok: false, error: res.error }; }
      this.store.removeAccount(id);
      return { ok: true };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  async flatten(id: string): Promise<Result<BrokerFlattenResult>> {
    try {
      const res = await firstValueFrom(this.api.flatten(id));
      if (res.error) { return { ok: false, error: res.error }; }
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
