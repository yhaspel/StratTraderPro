/** /backtest — walk-forward launcher + runs list (M09 §6.9).
 *
 * Left: a ReactiveForm over the AC-09-1 config — strategy picker (adapter-gated),
 * symbol multi-input (≤ 10), date range, train/test windows (``step`` auto-synced
 * to ``test``), mode/metric, initial cash, advanced costs + retention, a sizing
 * toggle, and a plain-`<textarea>` JSON param-grid editor with live validation.
 * Right/below: a server-paginated runs table with status chips, PBO, duration,
 * and a cancel button on active runs. Backend VALIDATION_ERROR details surface
 * inline. "Rerun with same config" prefills this form via the facade stash.
 */
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { ApiError } from '../../core/models/auth.models';
import {
  BacktestMetric,
  BacktestMode,
  BacktestRunRow,
  BacktestSizingMode,
  CreateBacktestRunBody,
} from '../../core/models/backtest.models';
import { BacktestFacade } from '../../abstraction/facades/backtest.facade';

const MODES: BacktestMode[] = ['rolling', 'anchored'];
const METRICS: BacktestMetric[] = ['sharpe', 'sortino', 'total_return', 'mar'];
const SIZING_MODES: BacktestSizingMode[] = ['production', 'fixed_qty_1'];
const ACTIVE_STATUSES = new Set(['QUEUED', 'RUNNING', 'CANCELLING']);

/** Error codes with a dedicated translated message under backtest.error.*. */
const KNOWN_ERRORS = new Set([
  'VALIDATION_ERROR',
  'BACKTEST_NO_ADAPTER',
  'BACKTEST_GRID_TOO_LARGE',
  'BACKTEST_LIMIT_CONCURRENT',
  'BACKTEST_DISABLED',
  'UNKNOWN',
]);

@Component({
  selector: 'app-backtest-launcher',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, TranslateModule, DatePipe],
  template: `
    <div class="mx-auto max-w-6xl p-6 space-y-8">
      <h1 class="text-2xl font-bold">{{ 'backtest.title' | translate }}</h1>

      <!-- ========== Launcher form ========== -->
      <section class="border rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-4">{{ 'backtest.launcher.title' | translate }}</h2>

        <form [formGroup]="form" (ngSubmit)="onSubmit()" class="space-y-5">
          <!-- Strategy picker -->
          <div>
            <label for="bt-strategy" class="block text-sm font-medium mb-1">{{ 'backtest.form.strategy' | translate }}</label>
            <select id="bt-strategy" formControlName="strategy" class="w-full border rounded px-3 py-2 text-sm">
              <option value="" disabled>{{ 'backtest.form.strategy_placeholder' | translate }}</option>
              @for (s of facade.strategies(); track s.id) {
                <option [value]="s.id" [disabled]="!s.has_adapter"
                        [title]="!s.has_adapter ? ('backtest.launcher.no_adapter_banner' | translate) : s.name">
                  {{ s.name }}@if (!s.has_adapter) { — {{ 'backtest.launcher.no_adapter_suffix' | translate }} }
                </option>
              }
            </select>
            @if (selectedNoAdapter()) {
              <p class="mt-1 text-xs text-amber-700" role="alert">⚠ {{ 'backtest.launcher.no_adapter_banner' | translate }}</p>
            } @else {
              <p class="mt-1 text-xs text-gray-400">{{ 'backtest.launcher.no_adapter_note' | translate }}</p>
            }
          </div>

          <!-- Symbols -->
          <div>
            <label for="bt-symbols" class="block text-sm font-medium mb-1">{{ 'backtest.form.symbols' | translate }}</label>
            <input id="bt-symbols" type="text" formControlName="symbols" autocomplete="off" spellcheck="false"
                   [placeholder]="'backtest.form.symbols_placeholder' | translate"
                   class="w-full border rounded px-3 py-2 font-mono text-sm" />
            <p class="mt-1 text-xs" [class.text-gray-400]="!symbolsError()" [class.text-red-700]="symbolsError()">
              {{ symbolsError() ? (symbolsError()! | translate) : ('backtest.form.symbols_help' | translate) }}
            </p>
          </div>

          <!-- Date range -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label for="bt-start" class="block text-sm font-medium mb-1">{{ 'backtest.form.start' | translate }}</label>
              <input id="bt-start" type="date" formControlName="start" class="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
              <label for="bt-end" class="block text-sm font-medium mb-1">{{ 'backtest.form.end' | translate }}</label>
              <input id="bt-end" type="date" formControlName="end" class="w-full border rounded px-3 py-2 text-sm" />
            </div>
          </div>

          <!-- Windows (step auto-synced to test) -->
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label for="bt-train" class="block text-sm font-medium mb-1">{{ 'backtest.form.train_window_days' | translate }}</label>
              <input id="bt-train" type="number" min="1" formControlName="train_window_days"
                     class="w-full border rounded px-3 py-2 font-mono text-sm" />
            </div>
            <div>
              <label for="bt-test" class="block text-sm font-medium mb-1">{{ 'backtest.form.test_window_days' | translate }}</label>
              <input id="bt-test" type="number" min="1" formControlName="test_window_days"
                     class="w-full border rounded px-3 py-2 font-mono text-sm" />
            </div>
            <div>
              <label for="bt-step" class="block text-sm font-medium mb-1">{{ 'backtest.form.step_days' | translate }}</label>
              <input id="bt-step" type="number" [value]="form.controls.test_window_days.value" readonly
                     class="w-full border rounded px-3 py-2 font-mono text-sm bg-gray-50 text-gray-500" />
              <p class="mt-1 text-xs text-gray-400">{{ 'backtest.form.step_help' | translate }}</p>
            </div>
          </div>

          <!-- Mode / metric / initial cash -->
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label for="bt-mode" class="block text-sm font-medium mb-1">{{ 'backtest.form.mode' | translate }}</label>
              <select id="bt-mode" formControlName="mode" class="w-full border rounded px-3 py-2 text-sm">
                @for (m of modes; track m) {
                  <option [value]="m">{{ ('backtest.mode.' + m) | translate }}</option>
                }
              </select>
            </div>
            <div>
              <label for="bt-metric" class="block text-sm font-medium mb-1">{{ 'backtest.form.metric' | translate }}</label>
              <select id="bt-metric" formControlName="metric" class="w-full border rounded px-3 py-2 text-sm">
                @for (m of metrics; track m) {
                  <option [value]="m">{{ ('backtest.metric.' + m) | translate }}</option>
                }
              </select>
            </div>
            <div>
              <label for="bt-cash" class="block text-sm font-medium mb-1">{{ 'backtest.form.initial_cash' | translate }}</label>
              <input id="bt-cash" type="number" min="1" step="1000" formControlName="initial_cash"
                     class="w-full border rounded px-3 py-2 font-mono text-sm" />
            </div>
          </div>

          <!-- Sizing toggle -->
          <div>
            <span class="block text-sm font-medium mb-1">{{ 'backtest.form.sizing' | translate }}</span>
            <div class="flex flex-wrap gap-3">
              @for (mode of sizingModes; track mode) {
                <label class="inline-flex items-center gap-2 text-sm border rounded px-3 py-1.5 cursor-pointer"
                       [class.bg-blue-50]="form.controls.sizing_mode.value === mode"
                       [class.border-blue-300]="form.controls.sizing_mode.value === mode">
                  <input type="radio" formControlName="sizing_mode" [value]="mode" class="rounded" />
                  {{ ('backtest.form.sizing_' + mode) | translate }}
                </label>
              }
            </div>
          </div>

          <!-- Param grid editor -->
          <div>
            <label for="bt-grid" class="block text-sm font-medium mb-1">{{ 'backtest.form.param_grid' | translate }}</label>
            <textarea id="bt-grid" rows="5" [value]="paramGridText()" (input)="onParamGridInput($event)"
                      class="w-full font-mono text-xs border rounded p-2" spellcheck="false" autocomplete="off"></textarea>
            @if (paramGridError(); as e) {
              <p class="mt-1 text-xs text-red-700">{{ e }}</p>
            } @else {
              <p class="mt-1 text-xs text-gray-400">{{ 'backtest.form.param_grid_help' | translate }}</p>
            }
          </div>

          <!-- Advanced: costs + retention -->
          <details class="border rounded-lg p-4">
            <summary class="text-sm font-medium cursor-pointer">{{ 'backtest.form.advanced' | translate }}</summary>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
              <div>
                <label for="bt-slip" class="block text-sm font-medium mb-1">{{ 'backtest.form.slippage_bps' | translate }}</label>
                <input id="bt-slip" type="number" min="1" step="0.5" formControlName="slippage_bps"
                       class="w-full border rounded px-3 py-2 font-mono text-sm" />
              </div>
              <div>
                <label for="bt-porder" class="block text-sm font-medium mb-1">{{ 'backtest.form.per_order_usd' | translate }}</label>
                <input id="bt-porder" type="number" min="0" step="0.01" formControlName="per_order_usd"
                       class="w-full border rounded px-3 py-2 font-mono text-sm" />
              </div>
              <div>
                <label for="bt-pshare" class="block text-sm font-medium mb-1">{{ 'backtest.form.per_share_usd' | translate }}</label>
                <input id="bt-pshare" type="number" min="0" step="0.001" formControlName="per_share_usd"
                       class="w-full border rounded px-3 py-2 font-mono text-sm" />
              </div>
              <div>
                <label for="bt-vpart" class="block text-sm font-medium mb-1">{{ 'backtest.form.volume_participation_pct' | translate }}</label>
                <input id="bt-vpart" type="number" min="0.001" max="100" step="1" formControlName="volume_participation_pct"
                       class="w-full border rounded px-3 py-2 font-mono text-sm" />
              </div>
              <div>
                <label for="bt-ret" class="block text-sm font-medium mb-1">{{ 'backtest.form.retention_days' | translate }}</label>
                <input id="bt-ret" type="number" min="1" max="365" step="1" formControlName="retention_days"
                       class="w-full border rounded px-3 py-2 font-mono text-sm" />
                <p class="mt-1 text-xs text-gray-400">{{ 'backtest.form.retention_help' | translate }}</p>
              </div>
            </div>
          </details>

          <!-- Submit + errors -->
          @if (submitError(); as err) {
            <div class="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm" role="alert">
              <p>
                @if (knownError(err.code)) {
                  {{ ('backtest.error.' + err.code) | translate }}
                } @else {
                  {{ err.message }}
                }
              </p>
              @if (errorDetails().length > 0) {
                <ul class="mt-1 list-disc list-inside text-xs">
                  @for (d of errorDetails(); track d) { <li>{{ d }}</li> }
                </ul>
              }
            </div>
          }

          <div class="flex items-center gap-3">
            <button type="submit" [disabled]="submitting() || form.invalid || !!paramGridError() || selectedNoAdapter() || !!symbolsError()"
                    class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50">
              {{ (submitting() ? 'backtest.launcher.submitting' : 'backtest.launcher.submit') | translate }}
            </button>
          </div>
        </form>
      </section>

      <!-- ========== Runs list ========== -->
      <section>
        <h2 class="text-lg font-semibold mb-3">{{ 'backtest.runs.title' | translate }}</h2>
        @if (facade.loading() && facade.runs().length === 0) {
          <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
        } @else if (facade.runs().length === 0) {
          <p class="text-sm text-gray-500">{{ 'backtest.runs.empty' | translate }}</p>
        } @else {
          <table class="w-full border border-gray-200 text-sm">
            <thead class="bg-gray-50 text-left">
              <tr>
                <th class="px-3 py-2">{{ 'backtest.runs.col.created' | translate }}</th>
                <th class="px-3 py-2">{{ 'backtest.runs.col.strategy' | translate }}</th>
                <th class="px-3 py-2">{{ 'backtest.runs.col.symbols' | translate }}</th>
                <th class="px-3 py-2">{{ 'backtest.runs.col.status' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'backtest.runs.col.pbo' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'backtest.runs.col.duration' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'backtest.runs.col.actions' | translate }}</th>
              </tr>
            </thead>
            <tbody>
              @for (r of facade.runs(); track r.id) {
                <tr class="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
                    tabindex="0" role="button"
                    [attr.aria-label]="r.strategy_name + ' — ' + r.symbols.join(', ')"
                    (keydown.enter)="onOpen(r.id)"
                    (keydown.space)="$event.preventDefault(); onOpen(r.id)">
                  <td class="px-3 py-2 whitespace-nowrap cursor-pointer" (click)="onOpen(r.id)">{{ r.created_at | date:'short' }}</td>
                  <td class="px-3 py-2 font-medium cursor-pointer" (click)="onOpen(r.id)">{{ r.strategy_name }}</td>
                  <td class="px-3 py-2 font-mono text-xs cursor-pointer" (click)="onOpen(r.id)">{{ r.symbols.join(', ') }}</td>
                  <td class="px-3 py-2 cursor-pointer" (click)="onOpen(r.id)">
                    <span class="text-xs px-2 py-0.5 rounded" [class]="statusClass(r.status)">
                      {{ ('backtest.status.' + r.status) | translate }}
                    </span>
                    @if (isActive(r.status)) { <span class="ml-1 text-xs text-gray-400 font-mono">{{ r.pct }}%</span> }
                  </td>
                  <td class="px-3 py-2 text-right font-mono" (click)="onOpen(r.id)">{{ fmtPbo(r.worst_pbo) }}</td>
                  <td class="px-3 py-2 text-right font-mono" (click)="onOpen(r.id)">{{ fmtDuration(r.duration_seconds) }}</td>
                  <td class="px-3 py-2 text-right">
                    @if (isActive(r.status)) {
                      <button type="button" (click)="onCancel(r); $event.stopPropagation()"
                              [disabled]="r.status === 'CANCELLING'"
                              class="px-2 py-1 border rounded text-xs hover:bg-gray-50 disabled:opacity-50">
                        {{ 'backtest.runs.cancel' | translate }}
                      </button>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>

          <div class="mt-4 flex items-center justify-between text-sm">
            <span class="text-gray-500">
              {{ 'backtest.runs.pagination' | translate:{ page: facade.page(), pages: facade.numPages(), total: facade.total() } }}
            </span>
            <div class="flex gap-2">
              <button type="button" (click)="onPrev()" [disabled]="facade.page() <= 1"
                      class="px-3 py-1 border rounded hover:bg-gray-50 disabled:opacity-50">
                {{ 'backtest.runs.prev' | translate }}
              </button>
              <button type="button" (click)="onNext()" [disabled]="facade.page() >= facade.numPages()"
                      class="px-3 py-1 border rounded hover:bg-gray-50 disabled:opacity-50">
                {{ 'backtest.runs.next' | translate }}
              </button>
            </div>
          </div>
        }
      </section>
    </div>
  `,
})
export class BacktestLauncherComponent implements OnInit {
  facade = inject(BacktestFacade);
  private fb = inject(FormBuilder);
  private router = inject(Router);
  private translate = inject(TranslateService);

  readonly modes = MODES;
  readonly metrics = METRICS;
  readonly sizingModes = SIZING_MODES;

  paramGridText = signal('{}');
  paramGridError = signal<string | null>(null);
  submitting = signal(false);
  submitError = signal<ApiError | null>(null);

  form = this.fb.nonNullable.group({
    strategy: ['', Validators.required],
    symbols: ['', Validators.required],
    start: [this._defaultStart()],
    end: [this._today()],
    train_window_days: [252, Validators.required],
    test_window_days: [63, Validators.required],
    mode: ['rolling' as BacktestMode],
    metric: ['sharpe' as BacktestMetric],
    initial_cash: [100000],
    slippage_bps: [5],
    per_order_usd: [0],
    per_share_usd: [0],
    volume_participation_pct: [10],
    sizing_mode: ['production' as BacktestSizingMode],
    retention_days: [90],
  });

  readonly errorDetails = computed(() => {
    const err = this.submitError();
    if (!err?.details) { return []; }
    return Object.entries(err.details).flatMap(([key, msgs]) => msgs.map(m => `${key}: ${m}`));
  });

  async ngOnInit(): Promise<void> {
    await this.facade.loadStrategies();
    this._applyRerunConfig();
    void this.facade.loadRuns(1);
  }

  onParamGridInput(ev: Event): void {
    const text = (ev.target as HTMLTextAreaElement).value;
    this.paramGridText.set(text);
    try {
      const obj = JSON.parse(text);
      if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) {
        this.paramGridError.set(this.translate.instant('backtest.form.param_grid_not_object'));
      } else {
        this.paramGridError.set(null);
      }
    } catch (e) {
      this.paramGridError.set(
        this.translate.instant('backtest.form.param_grid_invalid_json', { msg: (e as Error).message }),
      );
    }
  }

  async onSubmit(): Promise<void> {
    if (this.form.invalid || this.paramGridError() || this.symbolsError() || this.selectedNoAdapter()) { return; }
    this.submitError.set(null);
    this.submitting.set(true);
    try {
      const res = await this.facade.submitRun(this._buildBody());
      if (res.ok) {
        void this.router.navigate(['/backtest', res.value.id]);
      } else {
        this.submitError.set(res.error);
      }
    } finally {
      this.submitting.set(false);
    }
  }

  onOpen(id: string): void {
    void this.router.navigate(['/backtest', id]);
  }

  async onCancel(run: BacktestRunRow): Promise<void> {
    await this.facade.cancelRun(run.id);
  }

  onPrev(): void {
    if (this.facade.page() > 1) { void this.facade.loadRuns(this.facade.page() - 1); }
  }

  onNext(): void {
    if (this.facade.page() < this.facade.numPages()) { void this.facade.loadRuns(this.facade.page() + 1); }
  }

  knownError(code: string): boolean {
    return KNOWN_ERRORS.has(code);
  }

  /** True when the picked strategy has no registered Python adapter. */
  selectedNoAdapter(): boolean {
    const id = this.form.controls.strategy.value;
    const s = this.facade.strategies().find(x => x.id === id);
    return !!s && !s.has_adapter;
  }

  /** i18n key for a symbol-count validation error, or null when valid. */
  symbolsError(): string | null {
    const n = this._parseSymbols(this.form.controls.symbols.value).length;
    if (n === 0) { return 'backtest.form.symbols_empty'; }
    if (n > 10) { return 'backtest.form.symbols_too_many'; }
    return null;
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
      default: return 'bg-gray-100 text-gray-700'; // QUEUED
    }
  }

  fmtPbo(value: number | null): string {
    return value == null ? '—' : value.toFixed(2);
  }

  fmtDuration(seconds: number | null): string {
    if (seconds == null) { return '—'; }
    if (seconds < 60) { return `${seconds.toFixed(0)}s`; }
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }

  private _buildBody(): CreateBacktestRunBody {
    const v = this.form.getRawValue();
    const test = Number(v.test_window_days);
    const grid = JSON.parse(this.paramGridText() || '{}') as Record<string, number[]>;
    return {
      strategy: v.strategy,
      symbols: this._parseSymbols(v.symbols),
      start: v.start,
      end: v.end,
      tf: '1d',
      train_window_days: Number(v.train_window_days),
      test_window_days: test,
      step_days: test, // auto-synced (AC-09-1: step_days must equal test_window_days)
      mode: v.mode,
      metric: v.metric,
      initial_cash: Number(v.initial_cash),
      param_grid: grid,
      costs: {
        slippage_bps: Number(v.slippage_bps),
        per_order_usd: Number(v.per_order_usd),
        per_share_usd: Number(v.per_share_usd),
        volume_participation_pct: Number(v.volume_participation_pct),
      },
      sizing_mode: v.sizing_mode,
      retention_days: Number(v.retention_days),
    };
  }

  /** Split on comma/whitespace, upper-case, drop blanks, dedupe. */
  private _parseSymbols(raw: string): string[] {
    const seen: string[] = [];
    for (const part of raw.split(/[\s,]+/)) {
      const u = part.trim().toUpperCase();
      if (u && !seen.includes(u)) { seen.push(u); }
    }
    return seen;
  }

  /** Prefill from a "rerun with same config" stash, if present. */
  private _applyRerunConfig(): void {
    const cfg = this.facade.takeRerunConfig();
    if (!cfg) { return; }
    this.form.patchValue({
      strategy: cfg.strategy_id,
      symbols: cfg.symbols.join(', '),
      start: cfg.start,
      end: cfg.end,
      train_window_days: cfg.train_window_days,
      test_window_days: cfg.test_window_days,
      mode: cfg.mode,
      metric: cfg.metric,
      initial_cash: cfg.initial_cash,
      slippage_bps: cfg.costs.slippage_bps,
      per_order_usd: cfg.costs.per_order_usd,
      per_share_usd: cfg.costs.per_share_usd,
      volume_participation_pct: cfg.costs.volume_participation_pct,
      sizing_mode: cfg.sizing_mode,
      retention_days: cfg.retention_days,
    });
    this.paramGridText.set(JSON.stringify(cfg.param_grid ?? {}, null, 2));
    this.paramGridError.set(null);
  }

  private _today(): string {
    return new Date().toISOString().slice(0, 10);
  }

  private _defaultStart(): string {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 3);
    return d.toISOString().slice(0, 10);
  }
}
