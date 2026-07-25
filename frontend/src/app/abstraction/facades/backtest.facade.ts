/** BacktestFacade — bridges the BacktestApi + BacktestStore + UI (M09).
 *
 * Live progress rides the shared dashboard websocket: `start()` subscribes to
 * `backtest.*` frames and routes them into the store; the detail component adds
 * a 5s GET-poll fallback for when the socket is down. Report artifacts download
 * via the transient-object-URL blob pattern (mirrors OrdersFacade.exportCsv).
 */
import { Injectable, inject } from '@angular/core';
import { Subscription, firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import {
  BacktestProgress,
  BacktestReportFormat,
  BacktestRunConfig,
  BacktestRunDetail,
  BacktestRunListParams,
  BacktestStage,
  CreateBacktestRunBody,
} from '../../core/models/backtest.models';
import { BacktestApi } from '../../core/services/backtest.api';
import { DashboardEvent, DashboardWsService } from '../../core/services/ws.service';
import { BacktestStore } from '../stores/backtest.store';

type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };

@Injectable({ providedIn: 'root' })
export class BacktestFacade {
  private api = inject(BacktestApi);
  private store = inject(BacktestStore);
  private ws = inject(DashboardWsService);

  private sub: Subscription | null = null;

  readonly strategies = this.store.strategies;
  readonly runs = this.store.runs;
  readonly meta = this.store.meta;
  readonly filters = this.store.filters;
  readonly selected = this.store.selected;
  readonly report = this.store.report;
  readonly progress = this.store.progress;
  readonly rerunConfig = this.store.rerunConfig;
  readonly loading = this.store.loading;
  readonly error = this.store.error;
  readonly page = this.store.page;
  readonly numPages = this.store.numPages;
  readonly total = this.store.total;
  readonly connected = this.ws.connected;

  // ---- Strategy picker ----

  async loadStrategies(): Promise<void> {
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.strategies());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setStrategies(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  // ---- Runs list ----

  /** Load a page. Omitting ``filters`` reuses the last-applied set (paging). */
  async loadRuns(page = 1, filters?: BacktestRunListParams): Promise<void> {
    const active = filters ?? this.store.filters();
    this.store.setFilters(active);
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.listRuns({ ...active, page }));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setPage(res.data ?? [], res.meta ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  // ---- Create / cancel ----

  async submitRun(body: CreateBacktestRunBody): Promise<Result<BacktestRunDetail>> {
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.createRun(body));
      if (res.error) { return { ok: false, error: res.error }; }
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  async cancelRun(id: string): Promise<Result<{ id: string; status: string }>> {
    try {
      const res = await firstValueFrom(this.api.cancelRun(id));
      if (res.error) { return { ok: false, error: res.error }; }
      // Reflect the CANCELLING transition immediately in any list row + detail.
      this.store.patchStatus(id, 'CANCELLING');
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  // ---- Detail + report ----

  /** Initial load for the detail page (spinner + resets the prior report). */
  async openRun(id: string): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    this.store.setReport(null);
    try {
      await this._loadDetail(id);
    } finally {
      this.store.setLoading(false);
    }
  }

  /** Quiet background reload (poll fallback + terminal WS frames). */
  async refreshRun(id: string): Promise<void> {
    await this._loadDetail(id);
  }

  private async _loadDetail(id: string): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.getRun(id));
      if (res.error) { this.store.setError(res.error); return; }
      const run = res.data ?? null;
      this.store.setSelected(run);
      // Pull the report JSON for the charts once the run is complete.
      if (run && run.status === 'COMPLETED' && !this.store.report()) {
        await this._loadReport(id);
      }
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  private async _loadReport(id: string): Promise<void> {
    try {
      const report = await firstValueFrom(this.api.reportJson(id));
      this.store.setReport(report);
    } catch {
      // Report may be evicted (410) or not ready (404) — the charts simply
      // stay empty; the metrics/segments tables still render from the detail.
    }
  }

  closeDetail(): void {
    this.store.setSelected(null);
    this.store.setReport(null);
  }

  /** Download an artifact via a transient object URL (blob pattern). */
  async downloadReport(id: string, fmt: BacktestReportFormat): Promise<void> {
    try {
      const blob = await firstValueFrom(this.api.reportBlob(id, fmt));
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `backtest-${id}.${fmt}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  // ---- Rerun with same config ----

  stashRerun(config: BacktestRunConfig): void { this.store.setRerunConfig(config); }

  /** Read-and-clear the stashed config so the launcher only prefills once. */
  takeRerunConfig(): BacktestRunConfig | null {
    const cfg = this.store.rerunConfig();
    if (cfg) { this.store.setRerunConfig(null); }
    return cfg;
  }

  // ---- Live progress websocket ----

  /** Subscribe to `backtest.*` frames and open the shared socket (idempotent). */
  start(): void {
    if (this.sub) { return; }
    this.sub = this.ws.events$.subscribe(ev => this._apply(ev));
    this.ws.connect();
  }

  /** Drop the subscription and release our socket ref (refcounted — the socket
   * stays up while another subscriber, e.g. the dashboard, still holds a ref). */
  stop(): void {
    if (!this.sub) { return; }
    this.sub.unsubscribe();
    this.sub = null;
    this.ws.disconnect();  // P2-9: balance the connect() from start()
  }

  private _apply(ev: DashboardEvent): void {
    if (!ev.type.startsWith('backtest.')) { return; }
    const data = (ev.data ?? {}) as {
      run_id?: string; pct?: number; stage?: BacktestStage; eta_seconds?: number | null;
    };
    const runId = data.run_id;
    if (!runId) { return; }
    switch (ev.type) {
      case 'backtest.progress':
        this.store.applyProgress(runId, {
          pct: data.pct ?? 0,
          stage: data.stage ?? 'queued',
          eta_seconds: data.eta_seconds ?? null,
        } satisfies BacktestProgress);
        break;
      case 'backtest.completed':
        this.store.patchStatus(runId, 'COMPLETED');
        void this._refreshIfSelected(runId);
        break;
      case 'backtest.failed':
        this.store.patchStatus(runId, 'FAILED');
        void this._refreshIfSelected(runId);
        break;
      case 'backtest.cancelled':
        this.store.patchStatus(runId, 'CANCELLED');
        void this._refreshIfSelected(runId);
        break;
    }
  }

  /** After a terminal frame, reload the open detail so segments/summary/report fill in. */
  private _refreshIfSelected(runId: string): Promise<void> {
    if (this.store.selected()?.id === runId) { return this.refreshRun(runId); }
    return Promise.resolve();
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
