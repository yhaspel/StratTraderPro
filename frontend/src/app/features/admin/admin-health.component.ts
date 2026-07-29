/** /admin/health — full platform health cards plus external Grafana links.
 *
 * Grafana links come from `window.STP_CONFIG.grafanaUrl` (via ConfigService) and
 * are hidden entirely when the URL is empty. External links open in a new tab
 * with `rel="noopener"`.
 *
 * Industry styling: sub-nav with accent underline, blueprint status cards
 * (dot-chips for DB/Redis/broker streams, mono tabular numbers elsewhere).
 */
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { DatePipe, KeyValuePipe } from '@angular/common';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { SentimentBacklog } from '../../core/models/admin.models';
import { ConfigService } from '../../core/services/config.service';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { CardComponent } from '../shared/ui/card.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

@Component({
  selector: 'app-admin-health',
  standalone: true,
  imports: [
    DatePipe, KeyValuePipe, RouterLink, RouterLinkActive, TranslateModule,
    ImpersonationBannerComponent, CardComponent, PageHeaderComponent, StatusChipComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-6xl space-y-6 p-6">
      <app-page-header [heading]="'admin.health.title' | translate">
        <nav actions class="flex flex-wrap items-center gap-4 text-sm">
          <a routerLink="/admin" [routerLinkActiveOptions]="{ exact: true }"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.overview' | translate }}</a>
          <a routerLink="/admin/users"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.users' | translate }}</a>
          <a routerLink="/admin/audit"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.audit' | translate }}</a>
          <a routerLink="/admin/flags"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.flags' | translate }}</a>
          <a routerLink="/admin/health"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.health' | translate }}</a>
        </nav>
      </app-page-header>

      @if (grafanaUrl) {
        <a [href]="grafanaUrl" target="_blank" rel="noopener"
           class="inline-block text-sm text-accent-700 hover:underline">
          {{ 'admin.health.grafana' | translate }} ↗
        </a>
      }

      @if (admin.error(); as err) {
        <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">{{ err.message }}</div>
      }

      @if (admin.loading()) {
        <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
      }
      @if (!admin.loading() && admin.health(); as h) {
        <!-- ===== Status cards ===== -->
        <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
          <app-card>
            <div class="text-[10px] uppercase tracking-[.1em] text-neutral-700">{{ 'admin.health.db' | translate }}</div>
            <div class="mt-1.5">
              <app-status-chip [tone]="h.db_ok ? 'up' : 'down'" [dot]="true">
                {{ (h.db_ok ? 'admin.health.ok' : 'admin.health.down') | translate }}
              </app-status-chip>
            </div>
          </app-card>
          <app-card>
            <div class="text-[10px] uppercase tracking-[.1em] text-neutral-700">{{ 'admin.health.redis' | translate }}</div>
            <div class="mt-1.5">
              <app-status-chip [tone]="h.redis_ok ? 'up' : 'down'" [dot]="true">
                {{ (h.redis_ok ? 'admin.health.ok' : 'admin.health.down') | translate }}
              </app-status-chip>
            </div>
          </app-card>
          <app-card>
            <div class="text-[10px] uppercase tracking-[.1em] text-neutral-700">{{ 'admin.health.hmm_age' | translate }}</div>
            <div class="mt-1 font-mono text-[20px] font-semibold tabular-nums text-ink">{{ h.hmm_model_age_seconds != null ? h.hmm_model_age_seconds : '—' }}</div>
          </app-card>
          <app-card>
            <div class="text-[10px] uppercase tracking-[.1em] text-neutral-700">{{ 'admin.health.sentiment_backlog' | translate }}</div>
            <div class="mt-1 font-mono text-[20px] font-semibold tabular-nums text-ink">{{ backlogDepth(h.sentiment_backlog) }}</div>
            @if (backlogAgeMin(h.sentiment_backlog); as age) {
              <div class="mt-0.5 text-[11px] text-neutral-700">
                {{ 'admin.health.sentiment_oldest' | translate }}: <span class="font-mono tabular-nums">{{ age }}</span>
              </div>
            }
            @if (h.sentiment_backlog?.alert) {
              <div class="mt-1.5">
                <app-status-chip tone="warn">
                  <span aria-hidden="true">⚠&nbsp;</span>{{ 'admin.health.sentiment_alert' | translate }}
                </app-status-chip>
              </div>
            }
          </app-card>
        </div>

        <!-- ===== Regime data source (why the Market Regime card can be empty) ===== -->
        @if (h.regime_source_configured !== undefined) {
          <app-card>
            <h2 class="mb-2 font-heading text-lg font-semibold text-ink">{{ 'admin.health.regime_source' | translate }}</h2>
            <app-status-chip [tone]="h.regime_source_configured ? 'up' : 'warn'" [dot]="true">
              {{ (h.regime_source_configured ? 'admin.health.regime_source_ok' : 'admin.health.regime_source_missing') | translate }}
            </app-status-chip>
            @if (!h.regime_source_configured) {
              <p class="mt-2 text-[13px] text-neutral-700">{{ 'admin.health.regime_source_hint' | translate }}</p>
            }
          </app-card>
        }

        <!-- ===== Queue depths ===== -->
        <app-card>
          <h2 class="mb-2 font-heading text-lg font-semibold text-ink">{{ 'admin.health.queues' | translate }}</h2>
          @if (isEmpty(h.queue_depths)) {
            <p class="text-sm text-neutral-700">{{ 'admin.health.no_queues' | translate }}</p>
          } @else {
            <ul class="divide-y divide-divider text-[13px]">
              @for (q of h.queue_depths | keyvalue; track q.key) {
                <li class="flex justify-between py-1"><span class="font-mono">{{ q.key }}</span><span class="text-right font-mono tabular-nums">{{ q.value }}</span></li>
              }
            </ul>
          }
        </app-card>

        <!-- ===== Broker streams ===== -->
        <app-card>
          <h2 class="mb-2 font-heading text-lg font-semibold text-ink">{{ 'admin.health.broker_streams' | translate }}</h2>
          @if (isEmpty(h.broker_streams)) {
            <p class="text-sm text-neutral-700">{{ 'admin.health.no_streams' | translate }}</p>
          } @else {
            <ul class="divide-y divide-divider text-[13px]">
              <!-- key = stream state, value = how many accounts are in it. The
                   chip must take its tone from the STATE; the count is a number
                   beside it. Binding [status] to the count made every chip
                   neutral and labelled it "1". -->
              @for (s of h.broker_streams | keyvalue; track s.key) {
                <li class="flex items-center justify-between gap-3 py-1">
                  <app-status-chip [status]="s.key" [dot]="true">{{ s.key }}</app-status-chip>
                  <span class="font-mono tabular-nums">{{ s.value }}</span>
                </li>
              }
            </ul>
          }
        </app-card>

        <!-- ===== Active halts / overridden flags ===== -->
        <div class="grid gap-4 md:grid-cols-2">
          <app-card>
            <h2 class="mb-2 font-heading text-lg font-semibold text-ink">{{ 'admin.health.active_halts' | translate }}</h2>
            <!-- active_halts is an object {total, platform}, NOT a list — the old
                 "length === 0" test was always false on an object, so this card
                 rendered nothing at all. -->
            @if (!h.active_halts?.total) {
              <p class="text-sm text-neutral-700">{{ 'admin.health.no_halts' | translate }}</p>
            } @else {
              <div class="flex items-center gap-3">
                <span class="font-mono text-[20px] font-semibold tabular-nums text-ink">{{ h.active_halts?.total }}</span>
                @if (h.active_halts?.platform) {
                  <app-status-chip tone="down" [dot]="true">{{ 'admin.health.halt_platform' | translate }}</app-status-chip>
                }
              </div>
            }
          </app-card>
          <app-card>
            <h2 class="mb-2 font-heading text-lg font-semibold text-ink">{{ 'admin.health.overridden_flags' | translate }}</h2>
            <!-- flags_overridden is a COUNT, not a list (same drift). -->
            @if (!h.flags_overridden) {
              <p class="text-sm text-neutral-700">{{ 'admin.health.no_overrides' | translate }}</p>
            } @else {
              <p class="font-mono text-[20px] font-semibold tabular-nums text-ink">{{ h.flags_overridden }}</p>
            }
          </app-card>
        </div>

        <p class="text-xs text-neutral-700">{{ 'admin.health.generated' | translate }}: {{ h.generated_at | date:'medium' }}</p>
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

  /** Unscored-article count. `—` when the section degraded to `{}` server-side. */
  backlogDepth(b: SentimentBacklog | undefined): string {
    return b?.depth != null ? String(b.depth) : '—';
  }

  /** Oldest unscored article age, or '' when there is nothing pending (the
   * `@if (…; as age)` guard then skips the row rather than printing "0m"). */
  backlogAgeMin(b: SentimentBacklog | undefined): string {
    const age = b?.oldest_age_min;
    return age != null && age > 0 ? `${age}m` : '';
  }
}
