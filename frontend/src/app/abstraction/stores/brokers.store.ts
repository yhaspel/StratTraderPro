/** Signal-based store for the brokers feature. */
import { Injectable, computed, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import { BrokerAccount, BrokerStatus } from '../../core/models/brokers.models';

@Injectable({ providedIn: 'root' })
export class BrokersStore {
  private readonly _accounts = signal<BrokerAccount[]>([]);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly accounts = this._accounts.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  readonly count = computed(() => this._accounts().length);

  setLoading(loading: boolean) { this._loading.set(loading); }
  setError(err: ApiError | null) { this._error.set(err); }

  setAccounts(accounts: BrokerAccount[]) {
    this._accounts.set(accounts);
    this._error.set(null);
  }

  upsertAccount(account: BrokerAccount) {
    const next = this._accounts().filter(a => a.id !== account.id);
    next.push(account);
    next.sort((a, b) => Number(b.is_default) - Number(a.is_default) || a.created_at.localeCompare(b.created_at));
    this._accounts.set(next);
  }

  removeAccount(id: string) {
    this._accounts.set(this._accounts().filter(a => a.id !== id));
  }

  /** Patch stream/broker status onto the matching account (from status polls or ws). */
  applyStatus(status: BrokerStatus) {
    this._accounts.set(this._accounts().map(a =>
      a.id === status.id
        ? { ...a, status: status.broker_status, stream_status: status.stream_status }
        : a,
    ));
  }
}
