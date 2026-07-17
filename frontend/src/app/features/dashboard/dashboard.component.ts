/**
 * /dashboard — live trading dashboard (M04).
 *
 * Loads a snapshot (open positions, recent fills, broker status) then streams
 * realtime updates over the DashboardWsService via DashboardFacade. Everything
 * unsubscribes on destroy.
 */
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
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

/** Risk error codes with a dedicated translated message. */
const KNOWN_RISK_ERRORS = new Set(['HALT_LOCKED', 'MFA_REQUIRED', 'FORBIDDEN', 'UNKNOWN']);

@Component({
  selector: 'app-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslateModule, DatePipe, RegimeBadgeComponent, SentimentPanelComponent, OnboardingChecklistComponent],
  template: `
    <!-- ========== Halt banner (any active kill switch) ========== -->
    @if (risk.haltActive()) {
      <div class="bg-red-600 text-white px-4 py-3 text-sm font-semibold text-center" role="alert">
        {{ 'risk.halt_banner' | translate }}
      </div>
    }

    <div class="mx-auto max-w-6xl p-6 space-y-8">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">{{ 'dashboard.title' | translate }}</h1>
        <div class="flex items-center gap-3 text-sm">
          @if (auth.user()?.is_staff) {
            <a routerLink="/admin" class="text-blue-600 font-semibold hover:underline">
              {{ 'nav.admin' | translate }}
            </a>
          }
          <span class="inline-flex items-center gap-1">
            <span class="w-2 h-2 rounded-full"
                  [class.bg-green-500]="facade.connected()"
                  [class.bg-gray-400]="!facade.connected()"></span>
            {{ (facade.connected() ? 'dashboard.live' : 'dashboard.offline') | translate }}
          </span>
          <button type="button" (click)="openHalt()"
                  class="bg-red-600 text-white font-semibold px-4 py-2 rounded hover:bg-red-700">
            {{ 'risk.halt_my_trading' | translate }}
          </button>
        </div>
      </div>

      <!-- ========== Getting-started checklist (empty state, AC-10.5-5) ========== -->
      @if (onboarding.incomplete()) {
        <app-onboarding-checklist />
      }

      <!-- Honest 403: until MFA is enrolled every data endpoint 403s — say so
           once, rather than letting each panel lie with "No data yet". -->
      @if (mfaRequired()) {
        <div class="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="status">
          <a routerLink="/settings/security/mfa/setup" class="font-medium underline">
            {{ 'dashboard.mfa_required' | translate }}
          </a>
        </div>
      }

      <!-- ========== Market sentiment (M07) ========== -->
      <app-sentiment-panel />

      <!-- ========== Market regime (M06) ========== -->
      <app-regime-badge />

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">
          {{ err.message }}
        </div>
      }

      <!-- ========== Broker status ========== -->
      <section>
        <h2 class="text-lg font-semibold mb-3">{{ 'dashboard.broker_status.title' | translate }}</h2>
        @if (facade.brokerStatus().length === 0) {
          @if (mfaRequired()) {
            <p class="text-sm text-amber-700">{{ 'dashboard.requires_mfa' | translate }}</p>
          } @else {
            <p class="text-sm text-gray-500">{{ 'dashboard.broker_status.empty' | translate }}</p>
          }
        } @else {
          <div class="flex flex-wrap gap-3">
            @for (bs of facade.brokerStatus(); track bs.id) {
              <div class="flex items-center gap-2 border rounded px-3 py-2 text-sm">
                <span class="w-2 h-2 rounded-full"
                      [class.bg-green-500]="badge(bs.stream_status) === 'connected'"
                      [class.bg-amber-500]="badge(bs.stream_status) === 'degraded'"
                      [class.bg-red-500]="badge(bs.stream_status) === 'down'"></span>
                @switch (badge(bs.stream_status)) {
                  @case ('connected') { {{ 'brokers.status.connected' | translate }} }
                  @case ('degraded') { {{ 'brokers.status.degraded' | translate }} }
                  @default { {{ 'brokers.status.down' | translate }} }
                }
              </div>
            }
          </div>
        }
      </section>

      <!-- ========== Open positions ========== -->
      <section>
        <h2 class="text-lg font-semibold mb-3">{{ 'dashboard.positions.title' | translate }}</h2>
        @if (facade.loading()) {
          <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
        } @else if (facade.positions().length === 0) {
          @if (mfaRequired()) {
            <p class="text-sm text-amber-700">{{ 'dashboard.requires_mfa' | translate }}</p>
          } @else {
            <p class="text-sm text-gray-500">{{ 'dashboard.positions.empty' | translate }}</p>
          }
        } @else {
          <table class="w-full border border-gray-200 text-sm">
            <thead class="bg-gray-50 text-left">
              <tr>
                <th class="px-3 py-2">{{ 'dashboard.positions.col.symbol' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'dashboard.positions.col.qty' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'dashboard.positions.col.avg_cost' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'dashboard.positions.col.mark' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'dashboard.positions.col.pnl' | translate }}</th>
              </tr>
            </thead>
            <tbody>
              @for (p of facade.positions(); track p.id) {
                <tr class="border-t border-gray-100">
                  <td class="px-3 py-2 font-medium">{{ p.symbol }}</td>
                  <td class="px-3 py-2 text-right font-mono">{{ fmtQty(p.qty) }}</td>
                  <td class="px-3 py-2 text-right font-mono">{{ fmtMoney(p.avg_cost) }}</td>
                  <td class="px-3 py-2 text-right font-mono">{{ p.market_price ? fmtMoney(p.market_price) : '—' }}</td>
                  <td class="px-3 py-2 text-right font-mono"
                      [class.text-green-700]="pnlNum(p.unrealized_pnl) >= 0"
                      [class.text-red-700]="pnlNum(p.unrealized_pnl) < 0">
                    {{ p.unrealized_pnl != null ? fmtMoney(p.unrealized_pnl) : '—' }}
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      </section>

      <!-- ========== Today's fills ========== -->
      <section>
        <h2 class="text-lg font-semibold mb-3">{{ 'dashboard.fills.title' | translate }}</h2>
        @if (facade.fills().length === 0) {
          @if (mfaRequired()) {
            <p class="text-sm text-amber-700">{{ 'dashboard.requires_mfa' | translate }}</p>
          } @else {
            <p class="text-sm text-gray-500">{{ 'dashboard.fills.empty' | translate }}</p>
          }
        } @else {
          <ul class="divide-y border border-gray-200 rounded">
            @for (f of facade.fills(); track f.id) {
              <li class="px-3 py-2 flex items-center justify-between text-sm">
                <span class="font-medium">{{ f.symbol }}</span>
                <span class="font-mono text-gray-600">{{ fmtQty(f.qty) }} &#64; {{ fmtMoney(f.price) }}</span>
                <span class="text-xs text-gray-500">{{ f.ts | date:'shortTime' }}</span>
              </li>
            }
          </ul>
        }
      </section>

      <!-- ========== Dev-only test alert ========== -->
      @if (!isProd) {
        <section class="border-t pt-4">
          <button type="button" (click)="sendTestAlert()"
                  class="text-sm border border-dashed border-gray-400 text-gray-600 px-3 py-2 rounded hover:bg-gray-50">
            {{ 'dashboard.dev.send_test_alert' | translate }}
          </button>
          @if (toast()) {
            <span class="ml-3 text-sm text-green-700">✓ {{ 'dashboard.dev.alert_sent' | translate }}</span>
          }
        </section>
      }
    </div>

    <!-- ========== Halt-my-trading confirm + MFA prompt ========== -->
    @if (haltOpen()) {
      <div class="fixed inset-0 bg-black/40 z-40" (click)="cancelHalt()"></div>
      <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="bg-white rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
          <h2 class="text-lg font-bold text-red-700">{{ 'risk.halt_my_trading' | translate }}</h2>
          <p class="text-sm text-gray-600">{{ 'risk.halt_confirm' | translate }}</p>
          <form [formGroup]="mfaForm" (ngSubmit)="confirmHalt()" class="space-y-3">
            <div>
              <label class="block text-sm font-medium mb-1">{{ 'risk.mfa_prompt' | translate }}</label>
              <input type="text" inputmode="numeric" formControlName="mfa_code" maxlength="6"
                     autocomplete="one-time-code"
                     class="w-full border rounded px-3 py-2 font-mono text-sm" />
            </div>
            @if (haltError(); as err) {
              <p class="text-sm text-red-700">
                @if (knownRiskError(err.code)) {
                  {{ ('risk.error.' + err.code) | translate }}
                } @else {
                  {{ err.message }}
                }
              </p>
            }
            <div class="flex gap-3 justify-end">
              <button type="button" (click)="cancelHalt()"
                      class="px-4 py-2 rounded border text-sm hover:bg-gray-50">
                {{ 'common.cancel' | translate }}
              </button>
              <button type="submit" [disabled]="mfaForm.invalid"
                      class="bg-red-600 text-white px-4 py-2 rounded text-sm hover:bg-red-700 disabled:opacity-50">
                {{ 'risk.halt_my_trading' | translate }}
              </button>
            </div>
          </form>
        </div>
      </div>
    }
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

  fmtMoney(value: string): string {
    const n = Number(value);
    if (!isFinite(n)) { return value; }
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
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
