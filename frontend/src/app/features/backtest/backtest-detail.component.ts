/** /backtest/:id — run detail (M09 §6.9).
 *
 * Status header with a live progress bar (stage + ETA) driven by `backtest.*`
 * websocket frames, plus a 5s GET-poll fallback while the socket is down. Four
 * chart tabs (Equity, Drawdown, Monthly heatmap, Per-window) render from the
 * report JSON via **chart.js@4 + chartjs-chart-matrix**, imported DYNAMICALLY so
 * they land in a lazily-loaded chunk (keeps the initial bundle within budget).
 * Below: per-symbol metrics, the per-window segments table, artifact download
 * buttons (blob pattern), and "rerun with same config".
 */
import {
  Component, ElementRef, OnDestroy, OnInit, ViewChild, computed, effect, inject, signal,
} from '@angular/core';
import { CommonModule, JsonPipe } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import {
  BacktestReportSymbol,
  BacktestSegment,
  TimeseriesPoint,
} from '../../core/models/backtest.models';
import { BacktestFacade } from '../../abstraction/facades/backtest.facade';

type ChartTab = 'equity' | 'drawdown' | 'heatmap' | 'window';

const CHART_TABS: ChartTab[] = ['equity', 'drawdown', 'heatmap', 'window'];
const ACTIVE_STATUSES = new Set(['QUEUED', 'RUNNING', 'CANCELLING']);
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const POLL_MS = 5000;

/** Curated per-symbol metric columns (keys match report.py metric names). */
const METRIC_COLS: { key: string; kind: 'pct' | 'num' | 'int' }[] = [
  { key: 'total_return', kind: 'pct' },
  { key: 'cagr', kind: 'pct' },
  { key: 'sharpe', kind: 'num' },
  { key: 'sortino', kind: 'num' },
  { key: 'mar', kind: 'num' },
  { key: 'max_drawdown', kind: 'pct' },
  { key: 'trade_count', kind: 'int' },
];

@Component({
  selector: 'app-backtest-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, TranslateModule, JsonPipe],
  template: `
    <div class="mx-auto max-w-6xl p-6 space-y-6">
      <a routerLink="/backtest" class="text-sm text-blue-600 hover:underline">← {{ 'backtest.detail.back' | translate }}</a>

      @if (facade.loading() && !facade.selected()) {
        <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
      }

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">{{ err.message }}</div>
      }

      @if (facade.selected(); as run) {
        <!-- ========== Status header ========== -->
        <div class="border rounded-lg p-6 space-y-4">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 class="text-2xl font-bold">{{ run.strategy_name }}</h1>
              <p class="text-sm text-gray-500 font-mono">{{ run.symbols.join(', ') }}</p>
              <p class="text-xs text-gray-400 font-mono">{{ run.config.start }} → {{ run.config.end }} · {{ run.config.mode }} · {{ run.config.metric }}</p>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-xs px-2 py-1 rounded" [class]="statusClass(run.status)">
                {{ ('backtest.status.' + run.status) | translate }}
              </span>
              <button type="button" (click)="onRerun()"
                      class="px-3 py-1.5 border rounded text-sm hover:bg-gray-50">
                {{ 'backtest.detail.rerun' | translate }}
              </button>
              @if (isActive(run.status)) {
                <button type="button" (click)="onCancel()" [disabled]="run.status === 'CANCELLING'"
                        class="px-3 py-1.5 border rounded text-sm hover:bg-gray-50 disabled:opacity-50">
                  {{ 'backtest.runs.cancel' | translate }}
                </button>
              }
            </div>
          </div>

          <!-- Live progress -->
          @if (isActive(run.status)) {
            @if (liveProgress(); as p) {
              <div>
                <div class="flex items-center justify-between text-xs text-gray-500 mb-1">
                  <span>{{ ('backtest.stage.' + p.stage) | translate }}</span>
                  <span class="font-mono">
                    {{ p.pct }}%@if (p.eta_seconds != null) { · {{ 'backtest.detail.eta' | translate }} {{ fmtEta(p.eta_seconds) }} }
                  </span>
                </div>
                <div class="w-full bg-gray-100 rounded h-2 overflow-hidden">
                  <div class="bg-blue-600 h-2 transition-all" [style.width.%]="p.pct"></div>
                </div>
              </div>
            }
          }

          <!-- Failure detail -->
          @if (run.status === 'FAILED' && run.error_message) {
            <p class="text-sm text-red-700"><span class="font-mono">{{ run.error_code }}</span> — {{ run.error_message }}</p>
          }

          <!-- Downloads -->
          @if (run.status === 'COMPLETED') {
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs text-gray-500">{{ 'backtest.detail.downloads' | translate }}:</span>
              <button type="button" (click)="onDownload('json')" class="px-2 py-1 border rounded text-xs hover:bg-gray-50">
                {{ 'backtest.detail.download_json' | translate }}
              </button>
              <button type="button" (click)="onDownload('html')" class="px-2 py-1 border rounded text-xs hover:bg-gray-50">
                {{ 'backtest.detail.download_html' | translate }}
              </button>
              <button type="button" (click)="onDownload('pdf')" class="px-2 py-1 border rounded text-xs hover:bg-gray-50">
                {{ 'backtest.detail.download_pdf' | translate }}
              </button>
              @if (run.metrics_hash) {
                <span class="text-xs text-gray-400 font-mono ml-2">hash: {{ run.metrics_hash.slice(0, 12) }}…</span>
              }
            </div>
          }
        </div>

        <!-- ========== Charts ========== -->
        @if (facade.report(); as report) {
          <section class="border rounded-lg p-6 space-y-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="flex gap-1">
                @for (tab of chartTabs; track tab) {
                  <button type="button" (click)="setTab(tab)"
                          class="px-3 py-1.5 text-sm rounded border"
                          [class.bg-blue-600]="activeTab() === tab" [class.text-white]="activeTab() === tab">
                    {{ ('backtest.chart.' + tab) | translate }}
                  </button>
                }
              </div>
              @if (report.symbols.length > 1) {
                <select [value]="effectiveSymbol()" (change)="onSymbol($event)"
                        class="border rounded px-3 py-1.5 text-sm">
                  @for (s of report.symbols; track s.symbol) {
                    <option [value]="s.symbol">{{ s.symbol }}</option>
                  }
                </select>
              }
            </div>
            <div class="relative h-80">
              <canvas #chartCanvas></canvas>
            </div>
          </section>

          <!-- ========== Per-symbol metrics ========== -->
          <section>
            <h2 class="text-lg font-semibold mb-3">{{ 'backtest.detail.metrics' | translate }}</h2>
            <table class="w-full border border-gray-200 text-sm">
              <thead class="bg-gray-50 text-left">
                <tr>
                  <th class="px-3 py-2">{{ 'backtest.detail.col.symbol' | translate }}</th>
                  @for (c of metricCols; track c.key) {
                    <th class="px-3 py-2 text-right">{{ ('backtest.metric_col.' + c.key) | translate }}</th>
                  }
                  <th class="px-3 py-2 text-right">{{ 'backtest.detail.col.pbo' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (s of report.symbols; track s.symbol) {
                  <tr class="border-t border-gray-100">
                    <td class="px-3 py-2 font-medium">{{ s.symbol }}</td>
                    @for (c of metricCols; track c.key) {
                      <td class="px-3 py-2 text-right font-mono">{{ fmtMetric(s.metrics[c.key], c.kind) }}</td>
                    }
                    <td class="px-3 py-2 text-right font-mono"
                        [class.text-red-700]="s.pbo != null && s.pbo > 0.5">{{ fmtPbo(s.pbo) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </section>
        }

        <!-- ========== Segments (per-window) ========== -->
        @if (run.segments.length > 0) {
          <section>
            <h2 class="text-lg font-semibold mb-3">{{ 'backtest.detail.segments' | translate }}</h2>
            <table class="w-full border border-gray-200 text-sm">
              <thead class="bg-gray-50 text-left">
                <tr>
                  <th class="px-3 py-2">{{ 'backtest.detail.col.symbol' | translate }}</th>
                  <th class="px-3 py-2 text-right">{{ 'backtest.detail.col.window' | translate }}</th>
                  <th class="px-3 py-2">{{ 'backtest.detail.col.train' | translate }}</th>
                  <th class="px-3 py-2">{{ 'backtest.detail.col.test' | translate }}</th>
                  <th class="px-3 py-2">{{ 'backtest.detail.col.params' | translate }}</th>
                  <th class="px-3 py-2 text-right">{{ 'backtest.detail.col.sharpe' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (seg of run.segments; track $index) {
                  <tr class="border-t border-gray-100">
                    <td class="px-3 py-2 font-medium">{{ seg.symbol }}</td>
                    <td class="px-3 py-2 text-right font-mono">{{ seg.window_index }}</td>
                    <td class="px-3 py-2 font-mono text-xs whitespace-nowrap">{{ seg.train_start }} → {{ seg.train_end }}</td>
                    <td class="px-3 py-2 font-mono text-xs whitespace-nowrap">{{ seg.test_start }} → {{ seg.test_end }}</td>
                    <td class="px-3 py-2 font-mono text-xs">{{ seg.best_params | json }}</td>
                    <td class="px-3 py-2 text-right font-mono">{{ fmtMetric(seg.oos_metrics['sharpe'], 'num') }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </section>
        }
      }
    </div>
  `,
})
export class BacktestDetailComponent implements OnInit, OnDestroy {
  facade = inject(BacktestFacade);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  @ViewChild('chartCanvas') canvasRef?: ElementRef<HTMLCanvasElement>;

  readonly chartTabs = CHART_TABS;
  readonly metricCols = METRIC_COLS;

  runId = '';
  activeTab = signal<ChartTab>('equity');
  selectedSymbol = signal<string>('');

  private chart: any = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  /** Live progress: WS frame if present, else the last persisted run state. */
  readonly liveProgress = computed(() => {
    const p = this.facade.progress()[this.runId];
    if (p) { return p; }
    const sel = this.facade.selected();
    return sel ? { pct: sel.pct, stage: sel.stage, eta_seconds: null } : null;
  });

  /** The symbol to chart — explicit selection, or the report's first symbol. */
  readonly effectiveSymbol = computed(
    () => this.selectedSymbol() || this.facade.report()?.symbols[0]?.symbol || '',
  );

  constructor() {
    // Re-render whenever the report arrives or the tab/symbol changes.
    effect(() => {
      const report = this.facade.report();
      this.activeTab();
      this.effectiveSymbol();
      if (report) { this._scheduleRender(); }
    });
  }

  async ngOnInit(): Promise<void> {
    this.runId = this.route.snapshot.paramMap.get('id') ?? '';
    if (!this.runId) { return; }
    this.facade.start();
    await this.facade.openRun(this.runId);
    this._startPolling();
  }

  ngOnDestroy(): void {
    this.facade.stop();
    if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
    if (this.chart) { this.chart.destroy(); this.chart = null; }
    this.facade.closeDetail();
  }

  setTab(tab: ChartTab): void {
    this.activeTab.set(tab);
  }

  onSymbol(ev: Event): void {
    this.selectedSymbol.set((ev.target as HTMLSelectElement).value);
  }

  onRerun(): void {
    const sel = this.facade.selected();
    if (sel) { this.facade.stashRerun(sel.config); }
    void this.router.navigate(['/backtest']);
  }

  async onCancel(): Promise<void> {
    await this.facade.cancelRun(this.runId);
  }

  onDownload(fmt: 'json' | 'html' | 'pdf'): void {
    void this.facade.downloadReport(this.runId, fmt);
  }

  isActive(status: string): boolean {
    return ACTIVE_STATUSES.has(status);
  }

  statusClass(status: string): string {
    switch (status) {
      case 'COMPLETED': return 'bg-green-100 text-green-800';
      case 'FAILED': return 'bg-red-100 text-red-800';
      case 'CANCELLED': return 'bg-gray-100 text-gray-600';
      case 'RUNNING': return 'bg-blue-100 text-blue-800';
      case 'CANCELLING': return 'bg-amber-100 text-amber-800';
      default: return 'bg-gray-100 text-gray-700';
    }
  }

  fmtEta(seconds: number): string {
    if (seconds < 60) { return `${Math.round(seconds)}s`; }
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }

  fmtPbo(value: number | null): string {
    return value == null ? '—' : value.toFixed(2);
  }

  fmtMetric(value: number | null | undefined, kind: 'pct' | 'num' | 'int'): string {
    if (value == null || !isFinite(value)) { return '—'; }
    if (kind === 'pct') { return `${(value * 100).toFixed(2)}%`; }
    if (kind === 'int') { return String(Math.round(value)); }
    return value.toFixed(3);
  }

  // ---- Poll fallback ----

  private _startPolling(): void {
    if (this.pollTimer) { return; }
    this.pollTimer = setInterval(() => {
      const sel = this.facade.selected();
      if (!sel || !this.isActive(sel.status)) {
        // Terminal — stop polling.
        if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
        return;
      }
      // Only poll when the live socket is down (WS is the primary channel).
      if (!this.facade.connected()) { void this.facade.refreshRun(this.runId); }
    }, POLL_MS);
  }

  // ---- Charts (chart.js dynamically imported into the lazy chunk) ----

  private _scheduleRender(): void {
    // Defer to the next macrotask so the @if canvas is in the DOM.
    setTimeout(() => void this._renderChart(), 0);
  }

  private async _renderChart(): Promise<void> {
    const canvas = this.canvasRef?.nativeElement;
    const report = this.facade.report();
    if (!canvas || !report) { return; }
    const sym = report.symbols.find(s => s.symbol === this.effectiveSymbol()) ?? report.symbols[0];
    if (!sym) { return; }

    // Dynamic import keeps chart.js + the matrix plugin out of the initial bundle.
    const chartMod: any = await import('chart.js');
    const matrixMod: any = await import('chartjs-chart-matrix');
    const Chart = chartMod.Chart;
    Chart.register(...chartMod.registerables, matrixMod.MatrixController, matrixMod.MatrixElement);

    if (this.chart) { this.chart.destroy(); this.chart = null; }
    const config = this._buildConfig(this.activeTab(), sym);
    this.chart = new Chart(canvas, config);
  }

  private _buildConfig(tab: ChartTab, sym: BacktestReportSymbol): any {
    switch (tab) {
      case 'equity': return this._lineConfig(sym.equity, '#0d47a1', false);
      case 'drawdown': return this._lineConfig(sym.drawdown, '#c62828', true);
      case 'heatmap': return this._heatmapConfig(sym.equity);
      case 'window': return this._windowConfig(sym.windows);
    }
  }

  private _lineConfig(series: TimeseriesPoint[], color: string, fill: boolean): any {
    return {
      type: 'line',
      data: {
        labels: series.map(p => p[0].slice(0, 10)),
        datasets: [{
          data: series.map(p => p[1]),
          borderColor: color,
          backgroundColor: fill ? 'rgba(198,40,40,0.25)' : color,
          borderWidth: 1.2,
          pointRadius: 0,
          fill,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { maxTicksLimit: 8 } } },
      },
    };
  }

  private _windowConfig(windows: BacktestSegment[]): any {
    const data = windows.map(w => Number(w.oos_metrics?.['sharpe'] ?? 0));
    return {
      type: 'bar',
      data: {
        labels: windows.map(w => `#${w.window_index}`),
        datasets: [{
          data,
          backgroundColor: data.map(v => (v >= 0 ? '#2e7d32' : '#c62828')),
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
      },
    };
  }

  private _heatmapConfig(equity: TimeseriesPoint[]): any {
    const cells = this._monthlyReturns(equity);
    const years = [...new Set(cells.map(c => c.y))].sort();
    const maxAbs = cells.reduce((m, c) => Math.max(m, Math.abs(c.v)), 0.0001);
    return {
      type: 'matrix',
      data: {
        datasets: [{
          data: cells,
          backgroundColor: (ctx: any) => this._heatColor(ctx.raw.v, maxAbs),
          borderWidth: 1,
          borderColor: '#fff',
          width: ({ chart }: any) => (chart.chartArea?.width ?? 0) / 12 - 2,
          height: ({ chart }: any) => (chart.chartArea?.height ?? 0) / Math.max(1, years.length) - 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items: any[]) => `${items[0].raw.x} ${items[0].raw.y}`,
              label: (item: any) => `${(item.raw.v * 100).toFixed(2)}%`,
            },
          },
        },
        scales: {
          x: { type: 'category', labels: MONTHS, offset: true, grid: { display: false } },
          y: { type: 'category', labels: years.map(String), offset: true, grid: { display: false }, reverse: true },
        },
      },
    };
  }

  /** Month-end equity → month-over-month returns as matrix cells {x,y,v}. */
  private _monthlyReturns(equity: TimeseriesPoint[]): { x: string; y: string; v: number }[] {
    if (equity.length < 2) { return []; }
    // Last equity value per calendar month (month-end).
    const monthEnd = new Map<string, number>();
    for (const [iso, value] of equity) {
      monthEnd.set(iso.slice(0, 7), value); // YYYY-MM (iso is sorted ascending)
    }
    const keys = [...monthEnd.keys()].sort();
    const cells: { x: string; y: string; v: number }[] = [];
    for (let i = 1; i < keys.length; i++) {
      const prev = monthEnd.get(keys[i - 1])!;
      const cur = monthEnd.get(keys[i])!;
      if (prev === 0) { continue; }
      const [year, month] = keys[i].split('-');
      cells.push({ x: MONTHS[Number(month) - 1], y: year, v: cur / prev - 1 });
    }
    return cells;
  }

  private _heatColor(v: number, maxAbs: number): string {
    const t = Math.max(-1, Math.min(1, v / maxAbs));
    if (t >= 0) {
      const g = Math.round(255 - t * 100);
      return `rgb(${Math.round(255 - t * 209)}, ${Math.round(g + 20)}, ${Math.round(255 - t * 205)})`;
    }
    const a = -t;
    return `rgb(${Math.round(255)}, ${Math.round(255 - a * 200)}, ${Math.round(255 - a * 200)})`;
  }
}
