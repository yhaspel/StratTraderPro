/** Signal-based store for the M09 backtest feature — the strategy picker source,
 *  a server-paginated runs list, the selected run detail + report JSON, live
 *  progress keyed by run id, and a stashed config for "rerun with same config". */
import { Injectable, computed, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import {
  BacktestMeta,
  BacktestProgress,
  BacktestReport,
  BacktestRunConfig,
  BacktestRunDetail,
  BacktestRunListParams,
  BacktestRunRow,
  BacktestStatus,
  BacktestStrategyOption,
} from '../../core/models/backtest.models';

@Injectable({ providedIn: 'root' })
export class BacktestStore {
  private readonly _strategies = signal<BacktestStrategyOption[]>([]);
  private readonly _runs = signal<BacktestRunRow[]>([]);
  private readonly _meta = signal<BacktestMeta | null>(null);
  private readonly _filters = signal<BacktestRunListParams>({});
  private readonly _selected = signal<BacktestRunDetail | null>(null);
  private readonly _report = signal<BacktestReport | null>(null);
  private readonly _progress = signal<Record<string, BacktestProgress>>({});
  private readonly _rerunConfig = signal<BacktestRunConfig | null>(null);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly strategies = this._strategies.asReadonly();
  readonly runs = this._runs.asReadonly();
  readonly meta = this._meta.asReadonly();
  readonly filters = this._filters.asReadonly();
  readonly selected = this._selected.asReadonly();
  readonly report = this._report.asReadonly();
  readonly progress = this._progress.asReadonly();
  readonly rerunConfig = this._rerunConfig.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  readonly page = computed(() => this._meta()?.page ?? 1);
  readonly numPages = computed(() => this._meta()?.num_pages ?? 0);
  readonly total = computed(() => this._meta()?.total ?? 0);

  setLoading(loading: boolean) { this._loading.set(loading); }
  setError(err: ApiError | null) { this._error.set(err); }

  setStrategies(strategies: BacktestStrategyOption[]) { this._strategies.set(strategies); }

  setFilters(filters: BacktestRunListParams) { this._filters.set(filters); }

  setPage(runs: BacktestRunRow[], meta: BacktestMeta | null) {
    this._runs.set(runs);
    this._meta.set(meta);
  }

  setSelected(run: BacktestRunDetail | null) { this._selected.set(run); }
  setReport(report: BacktestReport | null) { this._report.set(report); }

  setRerunConfig(config: BacktestRunConfig | null) { this._rerunConfig.set(config); }

  /** Merge a `backtest.progress` frame; also patches the matching list row. */
  applyProgress(runId: string, progress: BacktestProgress): void {
    this._progress.set({ ...this._progress(), [runId]: progress });
    this._patchRow(runId, { pct: progress.pct, stage: progress.stage });
  }

  /** Patch a run's status on the list + selected detail (terminal WS frames). */
  patchStatus(runId: string, status: BacktestStatus): void {
    this._patchRow(runId, { status });
    const sel = this._selected();
    if (sel && sel.id === runId) { this._selected.set({ ...sel, status }); }
  }

  private _patchRow(runId: string, patch: Partial<BacktestRunRow>): void {
    const rows = this._runs();
    if (!rows.some(r => r.id === runId)) { return; }
    this._runs.set(rows.map(r => (r.id === runId ? { ...r, ...patch } : r)));
  }
}
