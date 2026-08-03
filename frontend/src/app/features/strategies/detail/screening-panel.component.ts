/**
 * Screening panel on /strategies/:id (M16 §6.6).
 *
 * States, in strict order of precedence:
 *   1. flag off / any screener endpoint 503s  -> panel hidden entirely
 *   2. no [screen] block                      -> honest empty state + guide
 *   3. block present but malformed            -> the line-numbered errors, verbatim
 *   4. no instance FMP key                    -> staff link / ask-admin copy
 *   5. ready                                  -> chips, Run, poll, results table
 *
 * Criteria are parsed SERVER-SIDE only (AC-16-10) — there is deliberately no
 * second `[screen]` parser in TypeScript.
 */
import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { ScreenerFacade } from '../../../abstraction/facades/screener.facade';
import { DataProvidersFacade } from '../../../abstraction/facades/data-providers.facade';
import { AuthStore } from '../../../abstraction/stores/auth.store';
import {
  ScreenCriteriaIssue,
  ScreenCriteriaMap,
  ScreenResultRow,
  ScreenRunDetail,
  ScreenRunSummary,
  isTerminal,
} from '../../../core/models/screener.models';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { EmptyStateComponent } from '../../shared/ui/empty-state.component';
import { HelpLinkComponent } from '../../shared/ui/help-link.component';
import { StatusChipComponent } from '../../shared/ui/status-chip.component';

/** A8 — a deliberate 2s cadence. Screens run seconds-to-a-minute and the run
 *  GET is cheap, so this is NOT the backtest detail page's 5s WS-down fallback. */
export const POLL_MS = 2000;

/** Error codes with dedicated `screener.error.*` copy. FEATURE_DISABLED is
 *  absent on purpose — a 503 hides the panel, so it never needs a message. */
const KNOWN_ERRORS = new Set([
  'FMP_NOT_CONFIGURED',
  'NO_SCREEN_CRITERIA',
  'SCREEN_CRITERIA_INVALID',
  'SCREEN_RUN_ACTIVE',
  'RATE_LIMITED',
  'FMP_RATE_LIMITED',
  'FMP_UNAVAILABLE',
  'SCREEN_TIME_CAP',
  'SCREEN_FAILED',
]);

const COMPACT = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 });

@Component({
  selector: 'app-screening-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    RouterLink,
    TranslateModule,
    ButtonComponent,
    CardComponent,
    EmptyStateComponent,
    HelpLinkComponent,
    StatusChipComponent,
  ],
  template: `
    <!-- State 1: flag off — render nothing at all. -->
    @if (!facade.disabled()) {
      <section class="mt-6" data-testid="screening-panel">
        <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 class="font-heading text-lg font-semibold text-ink" id="screening-heading">
            {{ 'screener.title' | translate }}
          </h2>
          <app-help-link slug="strategy-screening" [label]="'screener.guide' | translate" />
        </div>

        <app-card>
          @if (facade.loading() && !criteria()) {
            <p class="m-0 text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
          }

          <!-- State 3: malformed block — the author's own lint loop. -->
          @else if (issues().length) {
            <p class="m-0 text-sm text-neutral-700">{{ 'screener.invalid.intro' | translate }}</p>
            <ul class="mt-2 list-none p-0" data-testid="criteria-errors">
              @for (issue of issues(); track issue.line + issue.error) {
                <li class="border-l-2 border-down py-1 pl-3 text-[13px] text-down-deep">
                  <span class="font-mono">{{ 'screener.invalid.line' | translate }} {{ issue.line }}</span>
                  — {{ issue.error }}
                </li>
              }
            </ul>
            <app-help-link
              class="mt-3 inline-block"
              slug="strategy-screening"
              [label]="'screener.invalid.how_to_fix' | translate" />
          }

          <!-- Any other criteria-load error. -->
          @else if (loadError()) {
            <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
              @if (known(loadError())) {
                {{ ('screener.error.' + loadError()) | translate }}
              } @else {
                {{ loadErrorMessage() }}
              }
            </div>
          }

          <!-- State 2: no block. -->
          @else if (criteria() && !criteria()!.block_present) {
            <app-empty-state
              [heading]="'screener.empty.heading' | translate"
              [description]="'screener.empty.description' | translate" />
            <app-help-link
              class="mt-3 inline-block"
              slug="strategy-screening"
              [label]="'screener.empty.cta' | translate" />
          }

          <!-- States 4 + 5. -->
          @else if (criteria()?.block_present) {
            <!-- Criteria chips, straight from the server parse. -->
            <div class="flex flex-wrap gap-2" data-testid="criteria-chips">
              @for (chip of chips(); track chip) {
                <app-status-chip tone="neutral">{{ chip }}</app-status-chip>
              }
            </div>

            <!-- State 4: no instance FMP key. -->
            @if (keyMissing()) {
              <div class="mt-4 rounded-none border border-warn bg-warn-tint px-4 py-3 text-sm text-warn-deep"
                   role="status" data-testid="key-missing">
                {{ 'screener.error.FMP_NOT_CONFIGURED' | translate }}
                @if (isStaff()) {
                  <a routerLink="/settings/data-providers" class="ml-1 underline">
                    {{ 'screener.configure_link' | translate }}
                  </a>
                } @else {
                  <span class="ml-1">{{ 'data_providers.staff_only' | translate }}</span>
                }
              </div>
            } @else {
              <div class="mt-4 flex flex-wrap items-center gap-3">
                <app-button
                  [disabled]="busy()"
                  [loading]="busy()"
                  (clicked)="startRun()"
                  data-testid="run-screen">
                  {{ 'screener.run' | translate }}
                </app-button>
                @if (activeRun()) {
                  <span class="text-[13px] text-neutral-700" aria-live="polite" data-testid="run-status">
                    {{ ('screener.status.' + activeRun()!.status) | translate }}
                  </span>
                }
              </div>
            }

            <!-- Action error (the POST ladder's codes). -->
            @if (actionError(); as err) {
              <div class="mt-3 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep"
                   role="alert" data-testid="action-error">
                @if (known(err)) { {{ ('screener.error.' + err) | translate }} } @else { {{ actionErrorMessage() }} }
                @if (err === 'FMP_NOT_CONFIGURED' && isStaff()) {
                  <a routerLink="/settings/data-providers" class="ml-1 underline">
                    {{ 'screener.configure_link' | translate }}
                  </a>
                }
              </div>
            }

            <!-- Terminal run: degraded banner, then results. -->
            @if (current(); as run) {
              @if (run.status === 'FAILED') {
                <div class="mt-4 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep"
                     role="alert" data-testid="run-failed">
                  @if (known(run.error_code)) {
                    {{ ('screener.error.' + run.error_code) | translate }}
                  } @else {
                    {{ 'screener.error.generic' | translate }}
                  }
                </div>
              }

              @if (run.degraded) {
                <div class="mt-4" data-testid="degraded">
                  <app-status-chip tone="warn">{{ 'screener.degraded.chip' | translate }}</app-status-chip>
                  <p class="mt-1 text-[13px] text-neutral-700">{{ degradedCounts() }}</p>
                </div>
              }

              @if (run.status === 'DONE') {
                @if (run.results.length) {
                  <div class="mt-4 overflow-x-auto">
                    <table class="w-full border-collapse text-[13px]" data-testid="results-table">
                      <caption class="sr-only">{{ 'screener.table.caption' | translate }}</caption>
                      <thead>
                        <tr class="border-b border-divider text-left text-neutral-700">
                          <th scope="col" class="py-2 pr-3">{{ 'screener.table.symbol' | translate }}</th>
                          <th scope="col" class="py-2 pr-3">{{ 'screener.table.name' | translate }}</th>
                          <th scope="col" class="py-2 pr-3">{{ 'screener.table.exchange' | translate }}</th>
                          <th scope="col" class="py-2 pr-3">{{ 'screener.table.sector' | translate }}</th>
                          <th scope="col" class="py-2 pr-3 text-right">{{ 'screener.table.market_cap' | translate }}</th>
                          <th scope="col" class="py-2 pr-3 text-right">{{ 'screener.table.price' | translate }}</th>
                          <th scope="col" class="py-2 pr-3 text-right">{{ 'screener.table.volume' | translate }}</th>
                          <th scope="col" class="py-2 pr-3 text-right">{{ 'screener.table.from_high' | translate }}</th>
                          <th scope="col" class="py-2">{{ 'screener.table.trend' | translate }}</th>
                        </tr>
                      </thead>
                      <tbody>
                        @for (row of run.results; track row.symbol) {
                          <tr class="border-b border-divider">
                            <td class="py-2 pr-3 font-mono text-ink">{{ row.symbol }}</td>
                            <td class="py-2 pr-3 text-ink">{{ row.name }}</td>
                            <td class="py-2 pr-3 text-neutral-700">{{ row.exchange }}</td>
                            <td class="py-2 pr-3 text-neutral-700">{{ row.sector }}</td>
                            <td class="py-2 pr-3 text-right text-ink">{{ compact(row.market_cap) }}</td>
                            <td class="py-2 pr-3 text-right text-ink">{{ row.price ?? '—' }}</td>
                            <td class="py-2 pr-3 text-right text-ink">{{ compact(row.volume) }}</td>
                            <td class="py-2 pr-3 text-right text-ink">{{ pct(row.pct_from_52w_high) }}</td>
                            <td class="py-2">{{ trend(row) }}</td>
                          </tr>
                        }
                      </tbody>
                    </table>
                  </div>
                } @else {
                  <p class="mt-4 text-sm text-neutral-700" data-testid="no-matches">
                    {{ 'screener.no_matches' | translate }}
                  </p>
                }
              }
            }

            <!-- History: the last few runs, collapsed. -->
            @if (facade.runs().length) {
              <details class="mt-4">
                <summary class="cursor-pointer text-[13px] text-accent-700">
                  {{ 'screener.history' | translate }}
                </summary>
                <ul class="mt-2 list-none p-0" data-testid="run-history">
                  @for (r of facade.runs(); track r.id) {
                    <li class="flex flex-wrap gap-3 border-b border-divider py-1 text-[13px] text-neutral-700">
                      <span>{{ r.created_at }}</span>
                      <span>{{ ('screener.status.' + r.status) | translate }}</span>
                      <span>{{ 'screener.counts.returned' | translate }}: {{ r.counts.returned ?? 0 }}</span>
                    </li>
                  }
                </ul>
              </details>
            }
          }
        </app-card>
      </section>
    }
  `,
})
export class ScreeningPanelComponent implements OnInit, OnDestroy {
  @Input({ required: true }) strategyId = '';

  readonly facade = inject(ScreenerFacade);
  private providers = inject(DataProvidersFacade);
  private auth = inject(AuthStore);

  readonly criteria = this.facade.criteria;
  readonly current = signal<ScreenRunDetail | null>(null);
  readonly activeRun = signal<ScreenRunSummary | null>(null);
  readonly busy = signal(false);
  readonly actionError = signal<string | null>(null);
  readonly actionErrorMessage = signal<string>('');

  private timer: ReturnType<typeof setInterval> | null = null;

  readonly loadError = computed(() => this.facade.criteriaError()?.code ?? null);
  readonly loadErrorMessage = computed(() => this.facade.criteriaError()?.message ?? '');

  readonly issues = computed<ScreenCriteriaIssue[]>(() => {
    const err = this.facade.criteriaError();
    if (err?.code !== 'SCREEN_CRITERIA_INVALID') {
      return [];
    }
    // The screener's `details` is a line-numbered list, not the shared
    // Record<string, string[]> shape — narrow it here rather than widening the
    // app-wide ApiError type.
    return (err.details as unknown as ScreenCriteriaIssue[]) ?? [];
  });

  readonly isStaff = computed(() => !!this.auth.user()?.is_staff);

  /** State 4 pre-check: the panel says so BEFORE the user spends a click. */
  readonly keyMissing = computed(() => {
    const keys = this.providers.keys();
    return keys ? !keys.fmp.configured : false;
  });

  async ngOnInit(): Promise<void> {
    await this.facade.loadCriteria(this.strategyId);
    if (this.facade.disabled()) {
      return;
    }
    await Promise.all([
      this.facade.loadRuns(this.strategyId),
      this.providers.load().catch(() => undefined),
    ]);
    // A run may already be in flight from an earlier visit — resume polling.
    const active = this.facade.runs().find((r) => !isTerminal(r.status));
    if (active) {
      this.activeRun.set(active);
      this.startPolling(active.id);
    }
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  async startRun(): Promise<void> {
    this.busy.set(true);
    this.actionError.set(null);
    try {
      const res = await this.facade.run(this.strategyId);
      if (!res.ok) {
        this.actionError.set(res.error.code);
        this.actionErrorMessage.set(res.error.message);
        return;
      }
      this.activeRun.set({
        id: res.value.run_id,
        status: 'QUEUED',
        degraded: false,
        error_code: '',
        counts: {},
        created_at: null,
        started_at: null,
        finished_at: null,
      });
      this.startPolling(res.value.run_id);
    } finally {
      this.busy.set(false);
    }
  }

  /** Poll every 2s until the run reaches a terminal status (A8). */
  startPolling(runId: string): void {
    this.stopPolling();
    void this.poll(runId);
    this.timer = setInterval(() => void this.poll(runId), POLL_MS);
  }

  private stopPolling(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private async poll(runId: string): Promise<void> {
    const res = await this.facade.runDetail(this.strategyId, runId);
    if (!res.ok) {
      this.stopPolling();
      return;
    }
    this.current.set(res.value);
    this.activeRun.set(res.value);
    if (isTerminal(res.value.status)) {
      this.stopPolling();
      this.activeRun.set(null);
      void this.facade.loadRuns(this.strategyId);
    }
  }

  // -- view helpers ---------------------------------------------------------
  known(code: string | null): boolean {
    return !!code && KNOWN_ERRORS.has(code);
  }

  compact(value: number | null): string {
    return value === null || value === undefined ? '—' : COMPACT.format(value);
  }

  pct(value: number | null): string {
    return value === null || value === undefined ? '—' : `${value}%`;
  }

  trend(row: ScreenResultRow): string {
    const badges: string[] = [];
    if (row.above_sma_50) badges.push('50');
    if (row.above_sma_200) badges.push('200');
    const above = badges.length ? `>SMA ${badges.join('/')}` : '';
    const rising = row.sma200_rising ? '↑200' : '';
    return [above, rising].filter(Boolean).join('  ') || '—';
  }

  /** The per-cause line under the degraded chip — every non-zero cause named. */
  degradedCounts(): string {
    const c = this.current()?.counts ?? {};
    const parts: string[] = [];
    const add = (key: string, n?: number) => {
      if (n) parts.push(`${key}: ${n}`);
    };
    add('rate-limited', c.skipped_rate_limited);
    add('unavailable', c.skipped_unavailable);
    add('insufficient history', c.insufficient_history);
    return parts.join(' · ');
  }

  chips(): string[] {
    const c: ScreenCriteriaMap = this.criteria()?.criteria ?? {};
    const out: string[] = [];
    const range = (label: string, r?: { gte?: number; lte?: number }) => {
      if (!r) return;
      if (r.gte !== undefined && r.lte !== undefined) out.push(`${label} ${COMPACT.format(r.gte)}–${COMPACT.format(r.lte)}`);
      else if (r.gte !== undefined) out.push(`${label} ≥ ${COMPACT.format(r.gte)}`);
      else if (r.lte !== undefined) out.push(`${label} ≤ ${COMPACT.format(r.lte)}`);
    };
    range('Market cap', c.market_cap);
    range('Price', c.price);
    range('Volume', c.volume);
    range('Beta', c.beta);
    range('Dividend', c.dividend);
    if (c.sector) out.push(`Sector ${c.sector}`);
    if (c.industry) out.push(`Industry ${c.industry}`);
    if (c.exchange) out.push(`Exchange ${c.exchange}`);
    if (c.country) out.push(`Country ${c.country}`);
    if (c.etf) out.push('ETFs only');
    for (const n of c.above_sma ?? []) out.push(`Above SMA ${n}`);
    for (const n of c.sma_rising ?? []) out.push(`SMA ${n} rising`);
    if (c.near_52w_high !== undefined) out.push(`Within ${c.near_52w_high}% of 52w high`);
    if (c.limit !== undefined) out.push(`Limit ${c.limit}`);
    return out;
  }
}
