/**
 * /dashboard — live trading dashboard (M04).
 *
 * Loads a snapshot (open positions, recent fills, broker status) then streams
 * realtime updates over the DashboardWsService via DashboardFacade. Everything
 * unsubscribes on destroy.
 */
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { TranslateModule } from '@ngx-translate/core';
import { environment } from '../../../environments/environment';
import { StreamStatus } from '../../core/models/brokers.models';
import { DashboardFacade } from '../../abstraction/facades/dashboard.facade';
import { RegimeFacade } from '../../abstraction/facades/regime.facade';
import { RegimeBadgeComponent } from './regime-badge.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, TranslateModule, DatePipe, RegimeBadgeComponent],
  template: `
    <div class="mx-auto max-w-6xl p-6 space-y-8">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">{{ 'dashboard.title' | translate }}</h1>
        <div class="flex items-center gap-2 text-sm">
          <span class="inline-flex items-center gap-1">
            <span class="w-2 h-2 rounded-full"
                  [class.bg-green-500]="facade.connected()"
                  [class.bg-gray-400]="!facade.connected()"></span>
            {{ (facade.connected() ? 'dashboard.live' : 'dashboard.offline') | translate }}
          </span>
        </div>
      </div>

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
          <p class="text-sm text-gray-500">{{ 'dashboard.broker_status.empty' | translate }}</p>
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
          <p class="text-sm text-gray-500">{{ 'dashboard.positions.empty' | translate }}</p>
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
          <p class="text-sm text-gray-500">{{ 'dashboard.fills.empty' | translate }}</p>
        } @else {
          <ul class="divide-y border border-gray-200 rounded">
            @for (f of facade.fills(); track f.id) {
              <li class="px-3 py-2 flex items-center justify-between text-sm">
                <span class="font-medium">{{ f.symbol }}</span>
                <span class="font-mono text-gray-600">{{ fmtQty(f.qty) }} &#64; {{ fmtMoney(f.price) }}</span>
                <span class="text-xs text-gray-400">{{ f.ts | date:'shortTime' }}</span>
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
  `,
})
export class DashboardComponent implements OnInit, OnDestroy {
  facade = inject(DashboardFacade);
  regime = inject(RegimeFacade);

  readonly isProd = environment.production;
  toast = signal(false);
  private toastTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnInit(): void {
    void this.facade.loadSnapshot();
    this.facade.start();
    void this.regime.loadCurrent();
    void this.regime.loadHistory({ scope: 'MARKET' });
    void this.regime.loadModel();
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

  /** Dev stub — no backend dependency; just flashes a confirmation. */
  sendTestAlert(): void {
    this.toast.set(true);
    if (this.toastTimer) { clearTimeout(this.toastTimer); }
    this.toastTimer = setTimeout(() => this.toast.set(false), 3000);
  }
}
