/** ScreenerFacade — the Screening panel's only data source (M16 §6.6).
 *
 * Facade-only (no store), matching the ADR-062 `DataProvidersFacade` shape:
 * the state belongs to one panel, so a global store would be ceremony.
 * Components never inject `screener.api.ts` directly.
 */
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ScreenerApi } from '../../core/services/screener.api';
import { ApiError } from '../../core/models/auth.models';
import {
  ScreenCriteriaResponse,
  ScreenRunDetail,
  ScreenRunSummary,
} from '../../core/models/screener.models';

type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };

/** HTTP 503 from any screener endpoint means the feature flag is off, whatever
 *  the body says — the panel hides itself entirely (§6.6 state 1). */
export const FLAG_OFF_STATUS = 503;

@Injectable({ providedIn: 'root' })
export class ScreenerFacade {
  private api = inject(ScreenerApi);

  private readonly _criteria = signal<ScreenCriteriaResponse | null>(null);
  private readonly _criteriaError = signal<ApiError | null>(null);
  private readonly _disabled = signal(false);
  private readonly _loading = signal(false);
  private readonly _runs = signal<ScreenRunSummary[]>([]);

  readonly criteria = this._criteria.asReadonly();
  readonly criteriaError = this._criteriaError.asReadonly();
  /** True once any screener endpoint has answered 503. */
  readonly disabled = this._disabled.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly runs = this._runs.asReadonly();

  async loadCriteria(strategyId: string): Promise<void> {
    this._loading.set(true);
    // Reset EVERYTHING, not just the error. This facade is a root singleton
    // holding per-strategy state, so leaving the previous strategy's criteria
    // and runs in place meant navigating A -> B rendered A's chips and A's run
    // history under B's heading for the length of B's round-trip — and, if B's
    // runs GET failed, kept them indefinitely. Clearing `disabled` also lets a
    // re-enabled feature flag be picked up without a reload, which is the
    // documented roll-forward path for a mutable flag.
    this._criteriaError.set(null);
    this._criteria.set(null);
    this._runs.set([]);
    this._disabled.set(false);
    try {
      const res = await firstValueFrom(this.api.criteria(strategyId));
      if (res.error) {
        this._criteriaError.set(res.error);
        return;
      }
      this._criteria.set(res.data ?? null);
    } catch (err) {
      if (this._isFlagOff(err)) {
        this._disabled.set(true);
        return;
      }
      // A parse failure arrives as a 400 with line-numbered details — it is a
      // normal, author-facing state, not a crash.
      this._criteriaError.set(this._asError(err));
    } finally {
      this._loading.set(false);
    }
  }

  async loadRuns(strategyId: string, limit = 5): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.runs(strategyId, limit));
      this._runs.set(res.error ? [] : (res.data ?? []));
    } catch (err) {
      // Never leave a previous strategy's history on screen after a failure.
      this._runs.set([]);
      if (this._isFlagOff(err)) {
        this._disabled.set(true);
      }
    }
  }

  async run(strategyId: string): Promise<Result<{ run_id: string }>> {
    try {
      const res = await firstValueFrom(this.api.run(strategyId));
      if (res.error) {
        return { ok: false, error: res.error };
      }
      return { ok: true, value: res.data! };
    } catch (err) {
      if (this._isFlagOff(err)) {
        this._disabled.set(true);
      }
      return { ok: false, error: this._asError(err) };
    }
  }

  async runDetail(strategyId: string, runId: string): Promise<Result<ScreenRunDetail>> {
    try {
      const res = await firstValueFrom(this.api.run_detail(strategyId, runId));
      if (res.error) {
        return { ok: false, error: res.error };
      }
      return { ok: true, value: res.data! };
    } catch (err) {
      if (this._isFlagOff(err)) {
        this._disabled.set(true);
      }
      return { ok: false, error: this._asError(err) };
    }
  }

  private _isFlagOff(err: unknown): boolean {
    return (err as { status?: number })?.status === FLAG_OFF_STATUS;
  }

  private _asError(err: unknown): ApiError {
    const wrapped = err as {
      appError?: { apiError?: ApiError; message?: string };
      error?: { error?: ApiError };
      message?: string;
    };
    if (wrapped?.appError?.apiError?.code) {
      return wrapped.appError.apiError;
    }
    if (wrapped?.error?.error?.code) {
      return wrapped.error.error;
    }
    return {
      code: 'UNKNOWN',
      message: wrapped?.appError?.message ?? wrapped?.message ?? 'Unknown error',
    };
  }
}
