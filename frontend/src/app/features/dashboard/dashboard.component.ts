/**
 * /dashboard — live trading dashboard (M04, "Industry" restyle).
 *
 * Loads a snapshot (open positions, recent fills, broker status) then streams
 * realtime updates over the DashboardWsService via DashboardFacade. Everything
 * unsubscribes on destroy.
 *
 * Layout: page header (h1 + danger "Halt my trading") → getting-started →
 * MFA notice → sentiment + regime (2-col) → broker status chips → positions
 * table → fills. The halt banner moved into the shell (renders above the
 * header on every route); the Live dot moved into the shell header.
 */
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { environment } from '../../../environments/environment';
import { ApiError } from '../../core/models/auth.models';
import { StreamStatus } from '../../core/models/brokers.models';
import { AuthFacade } from '../../abstraction/facades/auth.facade';
import { DashboardFacade } from '../../abstraction/facades/dashboard.facade';
import { OnboardingFacade } from '../../abstraction/facades/onboarding.facade';
import { RegimeFacade } from '../../abstraction/facades/regime.facade';
import { RiskFacade } from '../../abstraction/facades/risk.facade';
import { SentimentFacade } from '../../abstraction/facades/sentiment.facade';
import { RegimeBadgeComponent } from './regime-badge.component';
import { SentimentPanelComponent } from './sentiment-panel.component';
import { OnboardingChecklistComponent } from '../shared/onboarding/onboarding-checklist.component';
import { BlueprintDirective } from '../shared/ui/blueprint.directive';
import { ButtonComponent } from '../shared/ui/button.component';
import { ModalComponent } from '../shared/ui/modal.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

/** Risk error codes with a dedicated translated message. */
const KNOWN_RISK_ERRORS = new Set(['HALT_LOCKED', 'MFA_REQUIRED', 'FORBIDDEN', 'UNKNOWN']);

/** |P&L| at or below this reads as neutral (muted) rather than up/down. */
const PNL_NEUTRAL_BAND = 0.05;

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, RouterLink, TranslateModule, DatePipe,
    RegimeBadgeComponent, SentimentPanelComponent, OnboardingChecklistComponent,
    BlueprintDirective, ButtonComponent, ModalComponent, PageHeaderComponent,
    StatusChipComponent,
  ],
  template: `
    <div class="space-y-5">
      <app-page-header [heading]="'dashboard.title' | translate">
        <app-button actions variant="danger" (clicked)="openHalt()">
          {{ 'risk.halt_my_trading' | translate }}
        </app-button>
      </app-page-header>

      <!-- ========== Getting-started checklist (empty state, AC-10.5-5) ========== -->
      @if (onboarding.incomplete()) {
        <app-onboarding-checklist />
      }

      <!-- Honest 403: until MFA is enrolled every data endpoint 403s — say so
           once, rather than letting each panel lie with "No data yet". -->
      @if (mfaRequired()) {
        <div class="border border-warn bg-warn-tint px-4 py-[11px] text-[13px] text-warn-deep" role="status">
          <a routerLink="/settings/security/mfa/setup" class="font-medium underline">
            {{ 'dashboard.mfa_required' | translate }}
          </a>
        </div>
      }

      <!-- ========== Sentiment (M07) + regime (M06), 2-col ========== -->
      <div class="grid grid-cols-1 gap-5 lg:grid-cols-[1.2fr_1fr]">
        <app-sentiment-panel />
        <app-regime-badge />
      </div>

      @if (facade.error(); as err) {
        <div class="border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
          {{ err.message }}
        </div>
      }

      <!-- ========== Broker status ========== -->
      <section>
        <h2 class="mb-3 font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
          {{ 'dashboard.broker_status.title' | translate }}
        </h2>
        @if (facade.brokerStatus().length === 0) {
          @if (mfaRequired()) {
            <p class="text-sm text-warn-deep">{{ 'dashboard.requires_mfa' | translate }}</p>
          } @else {
            <p class="text-sm text-neutral-700">{{ 'dashboard.broker_status.empty' | translate }}</p>
          }
        } @else {
          <div class="flex flex-wrap gap-3">
            @for (bs of facade.brokerStatus(); track bs.id) {
              <app-status-chip [status]="badge(bs.stream_status)" [dot]="true">
                @switch (badge(bs.stream_status)) {
                  @case ('connected') { {{ 'brokers.status.connected' | translate }} }
                  @case ('degraded') { {{ 'brokers.status.degraded' | translate }} }
                  @default { {{ 'brokers.status.down' | translate }} }
                }
              </app-status-chip>
            }
          </div>
        }
      </section>

      <!-- ========== Open positions ========== -->
      <section>
        <h2 class="mb-3 font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
          {{ 'dashboard.positions.title' | translate }}
        </h2>
        @if (facade.loading()) {
          <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
        } @else if (facade.positions().length === 0) {
          @if (mfaRequired()) {
            <p class="text-sm text-warn-deep">{{ 'dashboard.requires_mfa' | translate }}</p>
          } @else {
            <p class="text-sm text-neutral-700">{{ 'dashboard.positions.empty' | translate }}</p>
          }
        } @else {
          <div stpBlueprint class="bg-transparent">
            <table class="w-full text-[13px]">
              <thead class="text-left">
                <tr class="border-b border-divider">
                  <th class="px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'dashboard.positions.col.symbol' | translate }}</th>
                  <th class="px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'dashboard.positions.col.qty' | translate }}</th>
                  <th class="px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'dashboard.positions.col.avg_cost' | translate }}</th>
                  <th class="px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'dashboard.positions.col.mark' | translate }}</th>
                  <th class="px-4 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'dashboard.positions.col.pnl' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (p of facade.positions(); track p.id) {
                  <tr class="border-t border-divider first:border-t-0 hover:bg-surface">
                    <td class="px-4 py-2 font-semibold">{{ p.symbol }}</td>
                    <td class="px-3 py-2 text-right font-mono tabular-nums">{{ fmtQty(p.qty) }}</td>
                    <td class="px-3 py-2 text-right font-mono tabular-nums text-neutral-700">{{ fmtMoney(p.avg_cost) }}</td>
                    <td class="px-3 py-2 text-right font-mono tabular-nums text-neutral-700">{{ p.market_price ? fmtMoney(p.market_price) : '—' }}</td>
                    <td class="px-4 py-2 text-right font-mono font-medium tabular-nums" [ngClass]="pnlClass(p.unrealized_pnl)">
                      {{ p.unrealized_pnl != null ? fmtPnl(p.unrealized_pnl) : '—' }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </section>

      <!-- ========== Today's fills ========== -->
      <section>
        <h2 class="mb-3 font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
          {{ 'dashboard.fills.title' | translate }}
        </h2>
        @if (facade.fills().length === 0) {
          @if (mfaRequired()) {
            <p class="text-sm text-warn-deep">{{ 'dashboard.requires_mfa' | translate }}</p>
          } @else {
            <p class="text-sm text-neutral-700">{{ 'dashboard.fills.empty' | translate }}</p>
          }
        } @else {
          <div stpBlueprint class="bg-transparent px-4 py-2">
            <ul>
              @for (f of facade.fills(); track f.id) {
                <li class="flex items-center justify-between gap-3 border-t border-divider py-2 text-[13px] first:border-t-0">
                  <span class="font-semibold">{{ f.symbol }}</span>
                  <span class="font-mono tabular-nums text-neutral-700">{{ fmtQty(f.qty) }} &#64; {{ fmtMoney(f.price) }}</span>
                  <span class="font-mono text-xs text-neutral-700">{{ f.ts | date:'shortTime' }}</span>
                </li>
              }
            </ul>
          </div>
        }
      </section>

      <!-- ========== Dev-only test alert ========== -->
      @if (!isProd) {
        <section class="border-t border-divider pt-4">
          <button type="button" (click)="sendTestAlert()"
                  class="rounded-none border border-dashed border-neutral-400 px-3 py-2 text-sm text-neutral-700 hover:bg-surface">
            {{ 'dashboard.dev.send_test_alert' | translate }}
          </button>
          @if (toast()) {
            <span class="ml-3 text-sm text-accent-700">✓ {{ 'dashboard.dev.alert_sent' | translate }}</span>
          }
        </section>
      }
    </div>

    <!-- ========== Halt-my-trading confirm + MFA prompt ========== -->
    <app-modal
      [open]="haltOpen()"
      [heading]="'risk.halt_my_trading' | translate"
      [destructive]="true"
      [closeLabel]="'common.close' | translate"
      (closed)="cancelHalt()">
      <p class="mb-3 text-sm text-neutral-700">{{ 'risk.halt_confirm' | translate }}</p>
      <form [formGroup]="mfaForm" (ngSubmit)="confirmHalt()" class="space-y-3">
        <div>
          <label class="mb-1 block text-sm font-medium" for="halt-mfa-code">{{ 'risk.mfa_prompt' | translate }}</label>
          <input id="halt-mfa-code" type="text" inputmode="numeric" formControlName="mfa_code" maxlength="6"
                 autocomplete="one-time-code"
                 class="w-[140px] rounded-none border border-divider bg-transparent px-3 py-2 font-mono text-sm tracking-[.3em] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent" />
        </div>
        @if (haltError(); as err) {
          <p class="text-sm text-down-deep">
            @if (knownRiskError(err.code)) {
              {{ ('risk.error.' + err.code) | translate }}
            } @else {
              {{ err.message }}
            }
          </p>
        }
        <div class="flex justify-end gap-3">
          <app-button variant="ghost" (clicked)="cancelHalt()">{{ 'common.cancel' | translate }}</app-button>
          <app-button variant="danger" type="submit" [disabled]="mfaForm.invalid">
            {{ 'risk.halt_my_trading' | translate }}
          </app-button>
        </div>
      </form>
    </app-modal>
  `,
})
export class DashboardComponent implements OnInit, OnDestroy {
  facade = inject(DashboardFacade);
  regime = inject(RegimeFacade);
  sentiment = inject(SentimentFacade);
  risk = inject(RiskFacade);
  auth = inject(AuthFacade);
  onboarding = inject(OnboardingFacade);
  private fb = inject(FormBuilder);

  /** True when MFA is not yet enrolled — the reason every data panel 403s
   * (live-verified). Drives the honest "enable 2FA" state instead of the
   * misleading "No data yet" empties. */
  readonly mfaRequired = computed(() => this.onboarding.status()?.mfa_enrolled === false);

  readonly isProd = environment.production;
  toast = signal(false);
  private toastTimer: ReturnType<typeof setTimeout> | null = null;

  haltOpen = signal(false);
  haltError = signal<ApiError | null>(null);

  mfaForm = this.fb.nonNullable.group({
    mfa_code: ['', [Validators.required, Validators.minLength(6), Validators.maxLength(6)]],
  });

  ngOnInit(): void {
    void this.onboarding.load(); // refresh getting-started state on each visit (AC-10.5-5)
    void this.facade.loadSnapshot();
    this.facade.start();
    void this.regime.loadCurrent();
    void this.regime.loadHistory({ scope: 'MARKET' });
    void this.regime.loadModel();
    void this.sentiment.loadMarket();
    void this.sentiment.loadArticles();
    void this.risk.loadKillswitches();
  }

  ngOnDestroy(): void {
    this.facade.stop();
    if (this.toastTimer) { clearTimeout(this.toastTimer); }
  }

  badge(stream: StreamStatus): 'connected' | 'degraded' | 'down' {
    switch (stream) {
      case 'CONNECTED': return 'connected';
      case 'DEGRADED': return 'degraded';
      default: return 'down';
    }
  }

  pnlNum(value: string | null): number {
    const n = Number(value);
    return isFinite(n) ? n : 0;
  }

  /** P&L color: up/down outside the neutral band, muted inside it. */
  pnlClass(value: string | null): string {
    const n = this.pnlNum(value);
    if (n > PNL_NEUTRAL_BAND) { return 'text-up'; }
    if (n < -PNL_NEUTRAL_BAND) { return 'text-down'; }
    return 'text-neutral-700';
  }

  fmtMoney(value: string): string {
    const n = Number(value);
    if (!isFinite(n)) { return value; }
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
  }

  /** P&L is always signed (Industry trading-semantics rule). */
  fmtPnl(value: string): string {
    const n = Number(value);
    if (!isFinite(n)) { return value; }
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency: 'USD', signDisplay: 'always',
    }).format(n);
  }

  fmtQty(value: string): string {
    const n = Number(value);
    if (!isFinite(n)) { return value; }
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(n);
  }

  openHalt(): void {
    this.haltError.set(null);
    this.mfaForm.reset();
    this.haltOpen.set(true);
  }

  cancelHalt(): void {
    this.haltOpen.set(false);
    this.mfaForm.reset();
  }

  async confirmHalt(): Promise<void> {
    if (this.mfaForm.invalid) { return; }
    this.haltError.set(null);
    const { mfa_code } = this.mfaForm.getRawValue();
    const res = await this.risk.triggerHalt('USER', { flatten: true, mfa_code });
    if (res.ok) {
      this.haltOpen.set(false);
      this.mfaForm.reset();
    } else {
      // MFA_REQUIRED (wrong/expired code) or HALT_LOCKED — keep prompt open.
      this.haltError.set(res.error);
    }
  }

  knownRiskError(code: string): boolean {
    return KNOWN_RISK_ERRORS.has(code);
  }

  /** Dev stub — no backend dependency; just flashes a confirmation. */
  sendTestAlert(): void {
    this.toast.set(true);
    if (this.toastTimer) { clearTimeout(this.toastTimer); }
    this.toastTimer = setTimeout(() => this.toast.set(false), 3000);
  }
}
