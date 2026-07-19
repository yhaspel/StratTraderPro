/** /admin — Admin portal overview (M10).
 *
 * KPI cards summarise the platform health snapshot, plus a kill-switch card that
 * shows the active-halt banner and drives HALT / release. Engaging the halt
 * opens the typed-confirm HALT PLATFORM modal; releasing prompts for an MFA code
 * inline (no confirm phrase needed to release).
 *
 * Industry styling: sub-nav with accent underline on the active route, blueprint
 * KPI cards (status chips for DB/Redis, mono numbers for depths), danger Engage /
 * success Release (success is reserved for Release actions), and the shared
 * inline-confirm grammar (input → success confirm → secondary cancel).
 */
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { HaltPlatformModalComponent } from './halt-platform-modal.component';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

@Component({
  selector: 'app-admin-overview',
  standalone: true,
  imports: [
    RouterLink, RouterLinkActive, TranslateModule, HaltPlatformModalComponent,
    ImpersonationBannerComponent, TotpInputComponent,
    ButtonComponent, CardComponent, PageHeaderComponent, StatusChipComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    @if (admin.platformHalted()) {
      <div class="bg-down px-s4 py-s2 text-center font-heading text-sm font-semibold uppercase tracking-widest text-bg" role="alert">
        {{ 'admin.overview.halt_banner' | translate }}
      </div>
    }

    <div class="mx-auto max-w-6xl space-y-8 p-6">
      <app-page-header [heading]="'admin.overview.title' | translate">
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

      @if (admin.error(); as err) {
        <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
          {{ err.message }}
        </div>
      }

      <!-- ===== KPI cards ===== -->
      <section>
        <h2 class="mb-3 font-heading text-lg font-semibold text-ink">{{ 'admin.overview.kpis' | translate }}</h2>
        @if (admin.health(); as h) {
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
              <div class="text-[10px] uppercase tracking-[.1em] text-neutral-700">{{ 'admin.health.queue_total' | translate }}</div>
              <div class="mt-1 font-mono text-[20px] font-semibold tabular-nums text-ink">{{ queueTotal(h.queue_depths) }}</div>
            </app-card>
            <app-card>
              <div class="text-[10px] uppercase tracking-[.1em] text-neutral-700">{{ 'admin.health.sentiment_backlog' | translate }}</div>
              <div class="mt-1 font-mono text-[20px] font-semibold tabular-nums text-ink">{{ h.sentiment_backlog }}</div>
            </app-card>
          </div>
        } @else {
          @if (admin.error(); as err) {
            <p class="text-sm text-down" role="alert">
              @if (err.code === 'MFA_REQUIRED') {
                {{ 'admin.overview.kpis_mfa_required' | translate }}
              } @else {
                {{ 'admin.overview.kpis_error' | translate }}
              }
            </p>
          } @else {
            <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
          }
        }
      </section>

      <!-- ===== Kill-switch card ===== -->
      <app-card>
        <div class="flex items-center justify-between gap-4">
          <div>
            <h2 class="font-heading text-lg font-semibold text-ink">{{ 'admin.overview.killswitch' | translate }}</h2>
            <p class="text-sm" [class.text-down]="admin.platformHalted()" [class.text-up]="!admin.platformHalted()">
              {{ (admin.platformHalted() ? 'admin.overview.halted' : 'admin.overview.running') | translate }}
            </p>
            @if (admin.platform()?.note; as note) {
              <p class="mt-1 text-xs text-neutral-700">{{ note }}</p>
            }
          </div>
          @if (admin.platformHalted()) {
            <app-button variant="success" (clicked)="openRelease()">
              {{ 'admin.overview.release' | translate }}
            </app-button>
          } @else {
            <app-button variant="danger" (clicked)="haltOpen.set(true)">
              {{ 'admin.halt.engage' | translate }}
            </app-button>
          }
        </div>

        <!-- Inline release (MFA only; no confirm phrase) -->
        @if (releaseOpen()) {
          <div class="mt-4 space-y-3 border-t border-divider pt-4">
            <span class="block text-[11px] font-semibold uppercase tracking-wide text-accent-700">
              {{ 'admin.halt.mfa_label' | translate }}
            </span>
            <app-totp-input [ariaLabel]="'MFA code'" (codeChange)="releaseMfa.set($event)" [disabled]="releasing()" />
            @if (releaseError(); as err) {
              <p class="text-sm text-down">
                @if (err.code === 'MFA_REQUIRED') {
                  {{ 'admin.halt.error.MFA_REQUIRED' | translate }}
                } @else {
                  {{ err.message }}
                }
              </p>
            }
            <div class="flex justify-end gap-3">
              <app-button variant="success" [disabled]="releaseMfa().length !== 6 || releasing()"
                          [loading]="releasing()" (clicked)="release()">
                {{ (releasing() ? 'admin.overview.releasing' : 'admin.overview.release') | translate }}
              </app-button>
              <app-button variant="secondary" (clicked)="cancelRelease()">
                {{ 'common.cancel' | translate }}
              </app-button>
            </div>
          </div>
        }
      </app-card>
    </div>

    @if (haltOpen()) {
      <app-halt-platform-modal (closed)="haltOpen.set(false)" (halted)="onHalted()" />
    }
  `,
})
export class AdminOverviewComponent implements OnInit {
  admin = inject(AdminFacade);

  haltOpen = signal(false);
  releaseOpen = signal(false);
  releaseMfa = signal('');
  releasing = signal(false);
  releaseError = signal<ApiError | null>(null);

  ngOnInit(): void {
    void this.admin.loadHealth();
    void this.admin.loadPlatformStatus();
  }

  queueTotal(depths: Record<string, number>): number {
    return Object.values(depths ?? {}).reduce((a, b) => a + b, 0);
  }

  onHalted(): void {
    this.haltOpen.set(false);
  }

  openRelease(): void {
    this.releaseError.set(null);
    this.releaseMfa.set('');
    this.releaseOpen.set(true);
  }

  cancelRelease(): void {
    this.releaseOpen.set(false);
  }

  async release(): Promise<void> {
    if (this.releaseMfa().length !== 6) { return; }
    this.releaseError.set(null);
    this.releasing.set(true);
    try {
      const res = await this.admin.killswitch({
        engage: false,
        reason: '',
        mfa_code: this.releaseMfa(),
      });
      if (res.ok) {
        this.releaseOpen.set(false);
      } else {
        this.releaseError.set(res.error);
      }
    } finally {
      this.releasing.set(false);
    }
  }
}
