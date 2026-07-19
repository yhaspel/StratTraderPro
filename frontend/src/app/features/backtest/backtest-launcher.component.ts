/** /backtest — walk-forward launcher + runs list (M09 §6.9).
 *
 * Left: a ReactiveForm over the AC-09-1 config — strategy picker (adapter-gated),
 * symbol multi-input (≤ 10), date range, train/test windows (``step`` auto-synced
 * to ``test``), mode/metric, initial cash, advanced costs + retention, a sizing
 * toggle, and a plain-`<textarea>` JSON param-grid editor with live validation.
 * Right/below: a server-paginated runs table with status chips, PBO, duration,
 * and a cancel button on active runs. Backend VALIDATION_ERROR details surface
 * inline. "Rerun with same config" prefills this form via the facade stash.
 *
 * Visual layer: "Industry" design system (design_handoff/angular-migration-notes.md
 * §4 Backtest) — blueprint form card, Industry field grammar, `.seg` segmented
 * sizing control, dense runs table with status chips.
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
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';
import { BlueprintDirective } from '../shared/ui/blueprint.directive';

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
  imports: [
    CommonModule, ReactiveFormsModule, TranslateModule, DatePipe,
    ButtonComponent, CardComponent, PageHeaderComponent, StatusChipComponent, BlueprintDirective,
  ],
  template: `
    <div class="mx-auto max-w-6xl p-6">
      <app-page-header [heading]="'backtest.title' | translate" />

      <div class="grid items-start gap-s6 lg:grid-cols-[420px_minmax(0,1fr)]">
        <!-- ========== Launcher form ========== -->
        <app-card>
          <h2 class="mb-s3 font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
            {{ 'backtest.launcher.title' | translate }}
          </h2>

          <form [formGroup]="form" (ngSubmit)="onSubmit()" class="space-y-s4">
            <!-- Strategy picker -->
            <div>
              <label for="bt-strategy" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.strategy' | translate }}</label>
              <select id="bt-strategy" formControlName="strategy"
                      class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none">
                <option value="" disabled>{{ 'backtest.form.strategy_placeholder' | translate }}</option>
                @for (s of facade.strategies(); track s.id) {
                  <option [value]="s.id" [disabled]="!s.has_adapter"
                          [title]="!s.has_adapter ? ('backtest.launcher.no_adapter_banner' | translate) : s.name">
                    {{ s.name }}@if (!s.has_adapter) { — {{ 'backtest.launcher.no_adapter_suffix' | translate }} }
                  </option>
                }
              </select>
              @if (selectedNoAdapter()) {
                <p class="mt-1 text-[11px] text-warn-deep" role="alert">⚠ {{ 'backtest.launcher.no_adapter_banner' | translate }}</p>
              } @else {
                <p class="mt-1 text-[11px] text-neutral-700">{{ 'backtest.launcher.no_adapter_note' | translate }}</p>
              }
            </div>

            <!-- Symbols -->
            <div>
              <label for="bt-symbols" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.symbols' | translate }}</label>
              <input id="bt-symbols" type="text" formControlName="symbols" autocomplete="off" spellcheck="false"
                     [placeholder]="'backtest.form.symbols_placeholder' | translate"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
              <p class="mt-1 text-[11px]" [class.text-neutral-700]="!symbolsError()" [class.text-down]="symbolsError()">
                {{ symbolsError() ? (symbolsError()! | translate) : ('backtest.form.symbols_help' | translate) }}
              </p>
            </div>

            <!-- Date range -->
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label for="bt-start" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.start' | translate }}</label>
                <input id="bt-start" type="date" formControlName="start"
                       class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-[12px] text-ink focus:border-accent focus:outline-none" />
              </div>
              <div>
                <label for="bt-end" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.end' | translate }}</label>
                <input id="bt-end" type="date" formControlName="end"
                       class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-[12px] text-ink focus:border-accent focus:outline-none" />
              </div>
            </div>

            <!-- Windows (step auto-synced to test) -->
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label for="bt-train" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.train_window_days' | translate }}</label>
                <input id="bt-train" type="number" min="1" formControlName="train_window_days"
                       class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
              </div>
              <div>
                <label for="bt-test" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.test_window_days' | translate }}</label>
                <input id="bt-test" type="number" min="1" formControlName="test_window_days"
                       class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
              </div>
              <div>
                <label for="bt-step" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.step_days' | translate }}</label>
                <input id="bt-step" type="number" [value]="form.controls.test_window_days.value" readonly
                       class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-[13px] text-neutral-700 focus:border-accent focus:outline-none" />
                <p class="mt-1 text-[11px] text-neutral-700">{{ 'backtest.form.step_help' | translate }}</p>
              </div>
            </div>

            <!-- Mode / metric / initial cash -->
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label for="bt-mode" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.mode' | translate }}</label>
                <select id="bt-mode" formControlName="mode"
                        class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none">
                  @for (m of modes; track m) {
                    <option [value]="m">{{ ('backtest.mode.' + m) | translate }}</option>
                  }
                </select>
              </div>
              <div>
                <label for="bt-metric" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.metric' | translate }}</label>
                <select id="bt-metric" formControlName="metric"
                        class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none">
                  @for (m of metrics; track m) {
                    <option [value]="m">{{ ('backtest.metric.' + m) | translate }}</option>
                  }
                </select>
              </div>
              <div>
                <label for="bt-cash" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.initial_cash' | translate }}</label>
                <input id="bt-cash" type="number" min="1" step="1000" formControlName="initial_cash"
                       class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
              </div>
            </div>

            <!-- Sizing segmented control (Industry .seg grammar over the same radios) -->
            <div>
              <span class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.sizing' | translate }}</span>
              <div class="inline-flex rounded-none border border-divider">
                @for (mode of sizingModes; track mode; let first = $first) {
                  <label class="inline-flex cursor-pointer items-center px-3 py-1.5 text-[13px] leading-tight border-divider transition-colors focus-within:outline focus-within:outline-2 focus-within:-outline-offset-2 focus-within:outline-accent"
                         [class.border-l]="!first"
                         [ngClass]="form.controls.sizing_mode.value === mode ? 'bg-accent-700 text-bg' : 'bg-transparent text-ink hover:bg-neutral-200'">
                    <input type="radio" formControlName="sizing_mode" [value]="mode" class="sr-only" />
                    {{ ('backtest.form.sizing_' + mode) | translate }}
                  </label>
                }
              </div>
            </div>

            <!-- Param grid editor -->
            <div>
              <label for="bt-grid" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.param_grid' | translate }}</label>
              <textarea id="bt-grid" rows="5" [value]="paramGridText()" (input)="onParamGridInput($event)"
                        class="w-full rounded-none border border-divider bg-surface p-2.5 font-mono text-xs leading-relaxed text-ink focus:border-accent focus:outline-none"
                        spellcheck="false" autocomplete="off"></textarea>
              @if (paramGridError(); as e) {
                <p class="mt-1 text-[11px] text-down">{{ e }}</p>
              } @else {
                <p class="mt-1 text-[11px] text-neutral-700">{{ 'backtest.form.param_grid_help' | translate }}</p>
              }
            </div>

            <!-- Advanced: costs + retention -->
            <details class="rounded-none border border-divider px-3.5 py-2.5">
              <summary class="cursor-pointer text-[13px] font-medium text-neutral-700">{{ 'backtest.form.advanced' | translate }}</summary>
              <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label for="bt-slip" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.slippage_bps' | translate }}</label>
                  <input id="bt-slip" type="number" min="1" step="0.5" formControlName="slippage_bps"
                         class="min-h-[32px] w-full rounded-none border border-divider bg-surface px-2.5 py-1 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
                </div>
                <div>
                  <label for="bt-porder" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.per_order_usd' | translate }}</label>
                  <input id="bt-porder" type="number" min="0" step="0.01" formControlName="per_order_usd"
                         class="min-h-[32px] w-full rounded-none border border-divider bg-surface px-2.5 py-1 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
                </div>
                <div>
                  <label for="bt-pshare" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.per_share_usd' | translate }}</label>
                  <input id="bt-pshare" type="number" min="0" step="0.001" formControlName="per_share_usd"
                         class="min-h-[32px] w-full rounded-none border border-divider bg-surface px-2.5 py-1 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
                </div>
                <div>
                  <label for="bt-vpart" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.volume_participation_pct' | translate }}</label>
                  <input id="bt-vpart" type="number" min="0.001" max="100" step="1" formControlName="volume_participation_pct"
                         class="min-h-[32px] w-full rounded-none border border-divider bg-surface px-2.5 py-1 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
                </div>
                <div>
                  <label for="bt-ret" class="mb-1 block text-[12px] text-neutral-700">{{ 'backtest.form.retention_days' | translate }}</label>
                  <input id="bt-ret" type="number" min="1" max="365" step="1" formControlName="retention_days"
                         class="min-h-[32px] w-full rounded-none border border-divider bg-surface px-2.5 py-1 font-mono text-[13px] text-ink focus:border-accent focus:outline-none" />
                  <p class="mt-1 text-[11px] text-neutral-700">{{ 'backtest.form.retention_help' | translate }}</p>
                </div>
              </div>
            </details>

            <!-- Submit + errors -->
            @if (submitError(); as err) {
              <div class="rounded-none border border-down bg-down-tint px-3 py-2 text-sm text-down-deep" role="alert">
                <p>
                  @if (knownError(err.code)) {
                    {{ ('backtest.error.' + err.code) | translate }}
                  } @else {
                    {{ err.message }}
                  }
                </p>
                @if (errorDetails().length > 0) {
                  <ul class="mt-1 list-inside list-disc text-xs">
                    @for (d of errorDetails(); track d) { <li>{{ d }}</li> }
                  </ul>
                }
              </div>
            }

            <app-button type="submit" variant="primary" [frame]="true"
                        [loading]="submitting()"
                        [disabled]="form.invalid || !!paramGridError() || selectedNoAdapter() || !!symbolsError()">
              {{ (submitting() ? 'backtest.launcher.submitting' : 'backtest.launcher.submit') | translate }}
            </app-button>
          </form>
        </app-card>

        <!-- ========== Runs list ========== -->
        <section stpBlueprint class="bg-transparent">
          <h2 class="px-4 pb-2 pt-3.5 font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
            {{ 'backtest.runs.title' | translate }}
          </h2>
          @if (facade.loading() && facade.runs().length === 0) {
            <p class="px-4 pb-4 text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
          } @else if (facade.runs().length === 0) {
            <p class="px-4 pb-4 text-sm text-neutral-700">{{ 'backtest.runs.empty' | translate }}</p>
          } @else {
            <table class="w-full text-[13px]">
              <thead>
                <tr>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.runs.col.created' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.runs.col.strategy' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.runs.col.symbols' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.runs.col.status' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-right text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.runs.col.pbo' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-right text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.runs.col.duration' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-right text-[11px] font-medium uppercase tracking-[.08em] text-neutral-700">{{ 'backtest.runs.col.actions' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (r of facade.runs(); track r.id) {
                  <tr class="cursor-pointer border-t border-divider hover:bg-surface"
                      tabindex="0" role="button"
                      [attr.aria-label]="r.strategy_name + ' — ' + r.symbols.join(', ')"
                      (keydown.enter)="onOpen(r.id)"
                      (keydown.space)="$event.preventDefault(); onOpen(r.id)">
                    <td class="cursor-pointer whitespace-nowrap px-3 py-2 font-mono text-xs text-neutral-700" (click)="onOpen(r.id)">{{ r.created_at | date:'short' }}</td>
                    <td class="cursor-pointer px-3 py-2 font-bold" (click)="onOpen(r.id)">{{ r.strategy_name }}</td>
                    <td class="cursor-pointer px-3 py-2 font-mono text-xs text-neutral-700" (click)="onOpen(r.id)">{{ r.symbols.join(', ') }}</td>
                    <td class="cursor-pointer whitespace-nowrap px-3 py-2" (click)="onOpen(r.id)">
                      <app-status-chip [status]="r.status">{{ ('backtest.status.' + r.status) | translate }}</app-status-chip>
                      @if (isActive(r.status)) { <span class="ml-1.5 font-mono text-[11px] text-neutral-700">{{ r.pct }}%</span> }
                    </td>
                    <td class="px-3 py-2 text-right font-mono" (click)="onOpen(r.id)"
                        [class.text-down]="r.worst_pbo != null && r.worst_pbo > 0.5">
                      {{ fmtPbo(r.worst_pbo) }}
                      @if (r.worst_pbo != null && r.worst_pbo > 0.5) {
                        <span class="ml-1 font-sans text-[11px]" [attr.aria-label]="'high overfitting risk'">⚠ high</span>
                      }
                    </td>
                    <td class="px-3 py-2 text-right font-mono text-neutral-700" (click)="onOpen(r.id)">{{ fmtDuration(r.duration_seconds) }}</td>
                    <td class="px-3 py-2 text-right">
                      @if (isActive(r.status)) {
                        <app-button variant="secondary"
                                    [disabled]="r.status === 'CANCELLING'"
                                    (clicked)="$event.stopPropagation(); onCancel(r)">
                          {{ 'backtest.runs.cancel' | translate }}
                        </app-button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>

            <div class="flex items-center justify-between px-4 py-2.5">
              <span class="font-mono text-xs text-neutral-700">
                {{ 'backtest.runs.pagination' | translate:{ page: facade.page(), pages: facade.numPages(), total: facade.total() } }}
              </span>
              <div class="flex gap-2">
                <app-button variant="secondary" (clicked)="onPrev()" [disabled]="facade.page() <= 1">
                  {{ 'backtest.runs.prev' | translate }}
                </app-button>
                <app-button variant="secondary" (clicked)="onNext()" [disabled]="facade.page() >= facade.numPages()">
                  {{ 'backtest.runs.next' | translate }}
                </app-button>
              </div>
            </div>
          }
        </section>
      </div>
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
