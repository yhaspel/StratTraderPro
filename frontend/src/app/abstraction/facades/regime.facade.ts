/** RegimeFacade — bridges the RegimeApi + RegimeStore + UI (M06). */
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import { RegimeApi, RegimeHistoryParams } from '../../core/services/regime.api';
import { RegimeStore } from '../stores/regime.store';

@Injectable({ providedIn: 'root' })
export class RegimeFacade {
  private api = inject(RegimeApi);
  private store = inject(RegimeStore);

  readonly current = this.store.current;
  readonly history = this.store.history;
  readonly model = this.store.model;
  readonly loading = this.store.loading;
  readonly error = this.store.error;

  async loadCurrent(): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.current());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setCurrent(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async loadHistory(params?: RegimeHistoryParams): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.history(params));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setHistory(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  async loadModel(): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.model());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setModel(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
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
