/** /backtest/:id — run detail (M09 §6.9).
 *
 * Status header with a live progress bar (stage + ETA) driven by `backtest.*`
 * websocket frames, plus a 5s GET-poll fallback while the socket is down. Four
 * chart tabs (Equity, Drawdown, Monthly heatmap, Per-window) render from the
 * report JSON via **chart.js@4 + chartjs-chart-matrix**, imported DYNAMICALLY so
 * they land in a lazily-loaded chunk (keeps the initial bundle within budget).
 * Below: per-symbol metrics, the per-window segments table, artifact download
 * buttons (blob pattern), and "rerun with same config".
 *
 * Visual layer: "Industry" design system (design_handoff/angular-migration-notes.md
 * §4 Backtest) — blueprint cards, accent-underline chart tabs, token-driven chart
 * colors (equity = accent-700, drawdown = --down, bars/heatmap = --up/--down; all
 * read from the CSS custom properties at render time — never raw hexes).
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
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';
import { BlueprintDirective } from '../shared/ui/blueprint.directive';

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
  imports: [
    CommonModule, RouterLink, TranslateModule, JsonPipe,
    ButtonComponent, CardComponent, StatusChipComponent, BlueprintDirective,
  ],
  template: `
    <div class="mx-auto max-w-6xl space-y-6 p-6">
      <a routerLink="/backtest"
         class="inline-block w-fit rounded-none px-1 text-[13px] text-accent-700 transition-colors hover:bg-accent-100">
        ← {{ 'backtest.detail.back' | translate }}
      </a>

      @if (facade.loading() && !facade.selected()) {
        <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
      }

      @if (facade.error(); as err) {
        <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">{{ err.message }}</div>
      }

      @if (facade.selected(); as run) {
        <!-- ========== Status header ========== -->
        <app-card>
          <div class="space-y-3.5">
            <div class="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 class="font-heading text-[28px] font-semibold leading-[1.12] tracking-tight text-ink">{{ run.strategy_name }}</h1>
                <p class="mt-1 font-mono text-[13px] text-neutral-700">{{ run.symbols.join(', ') }}</p>
                <p class="mt-0.5 font-mono text-xs text-neutral-700">{{ run.config.start }} → {{ run.config.end }} · {{ run.config.mode }} · {{ run.config.metric }}</p>
              </div>
              <div class="flex items-center gap-2.5">
                <app-status-chip [status]="run.status">{{ ('backtest.status.' + run.status) | translate }}</app-status-chip>
                <app-button variant="secondary" (clicked)="onRerun()">
                  {{ 'backtest.detail.rerun' | translate }}
                </app-button>
                @if (isActive(run.status)) {
                  <app-button variant="secondary" [disabled]="run.status === 'CANCELLING'" (clicked)="onCancel()">
                    {{ 'backtest.runs.cancel' | translate }}
                  </app-button>
                }
              </div>
            </div>

            <!-- Live progress -->
            @if (isActive(run.status)) {
              @if (liveProgress(); as p) {
                <div>
                  <div class="mb-1 flex items-center justify-between text-[11px] text-neutral-700">
                    <span>{{ ('backtest.stage.' + p.stage) | translate }}</span>
                    <span class="font-mono">
                      {{ p.pct }}%@if (p.eta_seconds != null) { · {{ 'backtest.detail.eta' | translate }} {{ fmtEta(p.eta_seconds) }} }
                    </span>
                  </div>
                  <div class="h-1.5 w-full overflow-hidden rounded-none bg-surface">
                    <div class="h-full bg-accent transition-all" [style.width.%]="p.pct"></div>
                  </div>
                </div>
              }
            }

            <!-- Failure detail -->
            @if (run.status === 'FAILED' && run.error_message) {
              <p class="text-sm text-down"><span class="font-mono">{{ run.error_code }}</span> — {{ run.error_message }}</p>
            }

            <!-- Downloads -->
            @if (run.status === 'COMPLETED') {
              <div class="flex flex-wrap items-center gap-2.5 border-t border-divider pt-3">
                <span class="text-[10px] font-medium uppercase tracking-[.1em] text-accent-700">{{ 'backtest.detail.downloads' | translate }}</span>
                <app-button variant="secondary" (clicked)="onDownload('json')">
                  {{ 'backtest.detail.download_json' | translate }}
                </app-button>
                <app-button variant="secondary" (clicked)="onDownload('html')">
                  {{ 'backtest.detail.download_html' | translate }}
                </app-button>
                <app-button variant="secondary" (clicked)="onDownload('pdf')">
                  {{ 'backtest.detail.download_pdf' | translate }}
                </app-button>
                @if (run.metrics_hash) {
                  <span class="ml-2 font-mono text-[11px] text-neutral-700">{{ 'backtest.detail.hash' | translate }}: {{ run.metrics_hash.slice(0, 12) }}…</span>
                }
              </div>
            }
          </div>
        </app-card>

        <!-- ========== Charts ========== -->
        @if (facade.report(); as report) {
          <app-card>
            <div class="space-y-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div class="flex flex-1 gap-5 border-b border-divider">
                  @for (tab of chartTabs; track tab) {
                    <button type="button" (click)="setTab(tab)"
                            class="-mb-px border-b-2 pb-2.5 text-[13px] transition-colors"
                            [class.border-accent]="activeTab() === tab"
                            [class.text-ink]="activeTab() === tab"
                            [class.font-semibold]="activeTab() === tab"
                            [class.border-transparent]="activeTab() !== tab"
                            [class.text-neutral-700]="activeTab() !== tab">
                      {{ ('backtest.chart.' + tab) | translate }}
                    </button>
                  }
                </div>
                @if (report.symbols.length > 1) {
                  <select [value]="effectiveSymbol()" (change)="onSymbol($event)"
                          class="min-h-[32px] rounded-none border border-divider bg-surface px-2.5 py-1 text-sm text-ink focus:border-accent focus:outline-none">
                    @for (s of report.symbols; track s.symbol) {
                      <option [value]="s.symbol">{{ s.symbol }}</option>
                    }
                  </select>
                }
              </div>
              <div class="relative h-80">
                <canvas #chartCanvas role="img" [attr.aria-label]="chartAriaLabel()"></canvas>
              </div>
            </div>
          </app-card>

          <!-- ========== Per-symbol metrics ========== -->
          <section stpBlueprint class="bg-transparent">
            <h2 class="px-4 pb-2 pt-3.5 font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
              {{ 'backtest.detail.metrics' | translate }}
            </h2>
            <table class="w-full text-[13px]">
              <thead>
                <tr>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.detail.col.symbol' | translate }}</th>
                  @for (c of metricCols; track c.key) {
                    <th class="border-b border-divider px-3 py-2 text-right text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ ('backtest.metric_col.' + c.key) | translate }}</th>
                  }
                  <th class="border-b border-divider px-3 py-2 text-right text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.detail.col.pbo' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (s of report.symbols; track s.symbol) {
                  <tr class="border-t border-divider">
                    <td class="px-3 py-2 font-bold">{{ s.symbol }}</td>
                    @for (c of metricCols; track c.key) {
                      <td class="px-3 py-2 text-right font-mono" [class]="metricClass(c.key, s.metrics[c.key])">{{ fmtMetric(s.metrics[c.key], c.kind) }}</td>
                    }
                    <td class="px-3 py-2 text-right font-mono"
                        [class.text-down]="s.pbo != null && s.pbo > 0.5">
                      {{ fmtPbo(s.pbo) }}
                      @if (s.pbo != null && s.pbo > 0.5) {
                        <span class="ml-1 font-sans text-[11px] not-italic" [attr.aria-label]="'high overfitting risk'">⚠ high</span>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </section>
        }

        <!-- ========== Segments (per-window) ========== -->
        @if (run.segments.length > 0) {
          <section stpBlueprint class="bg-transparent">
            <h2 class="px-4 pb-2 pt-3.5 font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
              {{ 'backtest.detail.segments' | translate }}
            </h2>
            <table class="w-full text-[13px]">
              <thead>
                <tr>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.detail.col.symbol' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-right text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.detail.col.window' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.detail.col.train' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.detail.col.test' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.detail.col.params' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-right text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.detail.col.sharpe' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (seg of run.segments; track $index) {
                  <tr class="border-t border-divider">
                    <td class="px-3 py-2 font-bold">{{ seg.symbol }}</td>
                    <td class="px-3 py-2 text-right font-mono">{{ seg.window_index }}</td>
                    <td class="whitespace-nowrap px-3 py-2 font-mono text-xs text-neutral-700">{{ seg.train_start }} → {{ seg.train_end }}</td>
                    <td class="whitespace-nowrap px-3 py-2 font-mono text-xs text-neutral-700">{{ seg.test_start }} → {{ seg.test_end }}</td>
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

  /** Accessible name for the chart canvas (role="img"). Summarises the visible
   *  tab and symbol so screen-reader users know what the chart depicts. */
  readonly chartAriaLabel = computed<string>(() => {
    const tab = this.activeTab();
    const sym = this.effectiveSymbol();
    const desc: Record<ChartTab, string> = {
      equity: 'Equity curve over time',
      drawdown: 'Drawdown over time',
      heatmap: 'Monthly returns heatmap by year and month',
      window: 'Out-of-sample Sharpe ratio per walk-forward window',
    };
    return `${desc[tab]}${sym ? ` for ${sym}` : ''}.`;
  });

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

  /** Money/risk sign colour for the metrics table (green/red = money ONLY):
   *  total return by sign, max drawdown red when negative — as in the mockup. */
  metricClass(key: string, value: number | null | undefined): string {
    if (value == null || !isFinite(value) || value === 0) { return ''; }
    if (key === 'total_return') { return value > 0 ? 'text-up' : 'text-down'; }
    if (key === 'max_drawdown') { return value < 0 ? 'text-down' : ''; }
    return '';
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
    // Industry tokens resolved at render time — chart colors never hard-code hexes.
    // Equity is ACCENT (steel, machinery); green/red are money and risk only.
    const accent = this._cssVar('--color-accent-700');
    const up = this._cssVar('--up');
    const down = this._cssVar('--down');
    const surface = this._cssVar('--color-surface');
    const bg = this._cssVar('--color-bg');
    const grid = this._cssVar('--color-neutral-300');
    switch (tab) {
      case 'equity': return this._lineConfig(sym.equity, accent, false, grid);
      case 'drawdown': return this._lineConfig(sym.drawdown, down, true, grid);
      case 'heatmap': return this._heatmapConfig(sym.equity, { up, down, surface, bg });
      case 'window': return this._windowConfig(sym.windows, { up, down });
    }
  }

  private _lineConfig(series: TimeseriesPoint[], color: string, fill: boolean, grid: string): any {
    return {
      type: 'line',
      data: {
        labels: series.map(p => p[0].slice(0, 10)),
        datasets: [{
          data: series.map(p => p[1]),
          borderColor: color,
          backgroundColor: fill ? this._withAlpha(color, 0.18) : color,
          borderWidth: 1.2,
          pointRadius: 0,
          fill,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxTicksLimit: 8 }, grid: { color: grid } },
          y: { grid: { color: grid } },
        },
      },
    };
  }

  private _windowConfig(windows: BacktestSegment[], colors: { up: string; down: string }): any {
    const data = windows.map(w => Number(w.oos_metrics?.['sharpe'] ?? 0));
    return {
      type: 'bar',
      data: {
        labels: windows.map(w => `#${w.window_index}`),
        datasets: [{
          data,
          // Per-window bars are sign-colored — money/risk semantics.
          backgroundColor: data.map(v => (v >= 0 ? colors.up : colors.down)),
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
      },
    };
  }

  private _heatmapConfig(
    equity: TimeseriesPoint[],
    colors: { up: string; down: string; surface: string; bg: string },
  ): any {
    const cells = this._monthlyReturns(equity);
    const years = [...new Set(cells.map(c => c.y))].sort();
    const maxAbs = cells.reduce((m, c) => Math.max(m, Math.abs(c.v)), 0.0001);
    return {
      type: 'matrix',
      data: {
        datasets: [{
          data: cells,
          backgroundColor: (ctx: any) => this._heatColor(ctx.raw.v, maxAbs, colors),
          borderWidth: 1,
          borderColor: colors.bg,
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

  /** Diverging heatmap ramp: --down through --color-surface at zero to --up. */
  private _heatColor(
    v: number,
    maxAbs: number,
    colors: { up: string; down: string; surface: string },
  ): string {
    const t = Math.max(-1, Math.min(1, v / maxAbs));
    const end = t >= 0 ? colors.up : colors.down;
    return this._mix(colors.surface, end, Math.abs(t));
  }

  // ---- Token color plumbing (canvas needs concrete values, not var() refs) ----

  /** Resolve a CSS custom property from :root at render time. */
  private _cssVar(name: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  private _rgbOf(color: string): [number, number, number] | null {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color);
    if (!m) { return null; }
    let hex = m[1];
    if (hex.length === 3) { hex = hex.split('').map(c => c + c).join(''); }
    const n = parseInt(hex, 16);
    // eslint-disable-next-line no-bitwise
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  /** Token color + alpha (drawdown area fill). Falls through untouched when the
   *  token isn't a plain hex (e.g. in test environments without the stylesheet). */
  private _withAlpha(color: string, alpha: number): string {
    const rgb = this._rgbOf(color);
    return rgb ? `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})` : color;
  }

  /** Linear RGB interpolation between two token colors (t in [0, 1]). */
  private _mix(from: string, to: string, t: number): string {
    const a = this._rgbOf(from);
    const b = this._rgbOf(to);
    if (!a || !b) { return t > 0.5 ? to : from; }
    const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  }
}
