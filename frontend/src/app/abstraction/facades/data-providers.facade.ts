/** DataProvidersFacade — instance FMP/FRED key status + staff set/remove
 * (ADR-062). Facade-only (no store): state is used by the one settings page. */
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { DataProvidersApi } from '../../core/services/data-providers.api';
import { ApiError } from '../../core/models/auth.models';
import { DataProvider, DataProviderKeys } from '../../core/models/data-providers.models';

type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };

@Injectable({ providedIn: 'root' })
export class DataProvidersFacade {
  private api = inject(DataProvidersApi);

  private readonly _keys = signal<DataProviderKeys | null>(null);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);
  readonly keys = this._keys.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  async load(): Promise<void> {
    this._loading.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.status());
      if (res.error) { this._error.set(res.error); return; }
      this._keys.set(res.data ?? null);
    } catch (err) {
      this._error.set(this._asError(err));
    } finally {
      this._loading.set(false);
    }
  }

  /** Validate + save a key (staff). The refreshed statuses come back on the
   * same response, so success also updates `keys`. */
  async set(provider: DataProvider, apiKey: string): Promise<Result<DataProviderKeys>> {
    this._loading.set(true);
    try {
      const res = await firstValueFrom(this.api.set(provider, apiKey));
      if (res.error) { return { ok: false, error: res.error }; }
      const value = res.data!;
      this._keys.set(value);
      return { ok: true, value };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    } finally {
      this._loading.set(false);
    }
  }

  async remove(provider: DataProvider): Promise<Result<DataProviderKeys>> {
    this._loading.set(true);
    try {
      const res = await firstValueFrom(this.api.remove(provider));
      if (res.error) { return { ok: false, error: res.error }; }
      const value = res.data!;
      this._keys.set(value);
      return { ok: true, value };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    } finally {
      this._loading.set(false);
    }
  }

  private _asError(err: unknown): ApiError {
    const wrapped = err as { appError?: { apiError?: ApiError; message?: string }; message?: string };
    if (wrapped?.appError?.apiError?.code) { return wrapped.appError.apiError; }
    return { code: 'UNKNOWN', message: wrapped?.appError?.message ?? wrapped?.message ?? 'Unknown error' };
  }
}
