/** /admin/health — full platform health cards plus external Grafana links.
 *
 * Grafana links come from `window.STP_CONFIG.grafanaUrl` (via ConfigService) and
 * are hidden entirely when the URL is empty. External links open in a new tab
 * with `rel="noopener"`.
 */
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { DatePipe, KeyValuePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ConfigService } from '../../core/services/config.service';
import { ImpersonationBannerComponent } from './impersonation-banner.component';

@Component({
  selector: 'app-admin-health',
  standalone: true,
  imports: [DatePipe, KeyValuePipe, RouterLink, TranslateModule, ImpersonationBannerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-6xl p-6 space-y-6">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">{{ 'admin.health.title' | translate }}</h1>
        <a routerLink="/admin" class="text-sm text-blue-600 hover:underline">{{ 'admin.nav.back' | translate }}</a>
      </div>

      @if (grafanaUrl) {
        <a [href]="grafanaUrl" target="_blank" rel="noopener"
           class="inline-block text-sm text-blue-600 hover:underline">
          {{ 'admin.health.grafana' | translate }} ↗
        </a>
      }

      @if (admin.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">{{ err.message }}</div>
      }

      @if (admin.loading()) {
        <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
      }
      @if (!admin.loading() && admin.health(); as h) {
        <!-- ===== Status cards ===== -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="border rounded p-4">
            <div class="text-xs uppercase text-gray-500">{{ 'admin.health.db' | translate }}</div>
            <div class="text-lg font-bold" [class.text-green-700]="h.db_ok" [class.text-red-700]="!h.db_ok">
              {{ (h.db_ok ? 'admin.health.ok' : 'admin.health.down') | translate }}
            </div>
          </div>
          <div class="border rounded p-4">
            <div class="text-xs uppercase text-gray-500">{{ 'admin.health.redis' | translate }}</div>
            <div class="text-lg font-bold" [class.text-green-700]="h.redis_ok" [class.text-red-700]="!h.redis_ok">
              {{ (h.redis_ok ? 'admin.health.ok' : 'admin.health.down') | translate }}
            </div>
          </div>
          <div class="border rounded p-4">
            <div class="text-xs uppercase text-gray-500">{{ 'admin.health.hmm_age' | translate }}</div>
            <div class="text-lg font-bold font-mono">{{ h.hmm_model_age_seconds != null ? h.hmm_model_age_seconds : '—' }}</div>
          </div>
          <div class="border rounded p-4">
            <div class="text-xs uppercase text-gray-500">{{ 'admin.health.sentiment_backlog' | translate }}</div>
            <div class="text-lg font-bold font-mono">{{ h.sentiment_backlog }}</div>
          </div>
        </div>

        <!-- ===== Queue depths ===== -->
        <section class="border rounded p-4">
          <h2 class="text-lg font-semibold mb-2">{{ 'admin.health.queues' | translate }}</h2>
          @if (isEmpty(h.queue_depths)) {
            <p class="text-sm text-gray-500">{{ 'admin.health.no_queues' | translate }}</p>
          } @else {
            <ul class="text-sm divide-y">
              @for (q of h.queue_depths | keyvalue; track q.key) {
                <li class="py-1 flex justify-between"><span class="font-mono">{{ q.key }}</span><span class="font-mono">{{ q.value }}</span></li>
              }
            </ul>
          }
        </section>

        <!-- ===== Broker streams ===== -->
        <section class="border rounded p-4">
          <h2 class="text-lg font-semibold mb-2">{{ 'admin.health.broker_streams' | translate }}</h2>
          @if (isEmpty(h.broker_streams)) {
            <p class="text-sm text-gray-500">{{ 'admin.health.no_streams' | translate }}</p>
          } @else {
            <ul class="text-sm divide-y">
              @for (s of h.broker_streams | keyvalue; track s.key) {
                <li class="py-1 flex justify-between"><span class="font-mono">{{ s.key }}</span><span>{{ s.value }}</span></li>
              }
            </ul>
          }
        </section>

        <!-- ===== Active halts / overridden flags ===== -->
        <div class="grid md:grid-cols-2 gap-4">
          <section class="border rounded p-4">
            <h2 class="text-lg font-semibold mb-2">{{ 'admin.health.active_halts' | translate }}</h2>
            @if (h.active_halts.length === 0) {
              <p class="text-sm text-gray-500">{{ 'admin.health.no_halts' | translate }}</p>
            } @else {
              <ul class="text-sm list-disc list-inside">
                @for (halt of h.active_halts; track halt) { <li>{{ halt }}</li> }
              </ul>
            }
          </section>
          <section class="border rounded p-4">
            <h2 class="text-lg font-semibold mb-2">{{ 'admin.health.overridden_flags' | translate }}</h2>
            @if (h.flags_overridden.length === 0) {
              <p class="text-sm text-gray-500">{{ 'admin.health.no_overrides' | translate }}</p>
            } @else {
              <ul class="text-sm list-disc list-inside font-mono">
                @for (fl of h.flags_overridden; track fl) { <li>{{ fl }}</li> }
              </ul>
            }
          </section>
        </div>

        <p class="text-xs text-gray-500">{{ 'admin.health.generated' | translate }}: {{ h.generated_at | date:'medium' }}</p>
      }
    </div>
  `,
})
export class AdminHealthComponent implements OnInit {
  admin = inject(AdminFacade);
  private config = inject(ConfigService);

  readonly grafanaUrl = this.config.grafanaUrl;

  ngOnInit(): void {
    void this.admin.loadHealth();
  }

  isEmpty(obj: Record<string, unknown>): boolean {
    return !obj || Object.keys(obj).length === 0;
  }
}
