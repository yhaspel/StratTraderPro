/** /admin — Admin portal overview (M10).
 *
 * KPI cards summarise the platform health snapshot, plus a kill-switch card that
 * shows the active-halt banner and drives HALT / release. Engaging the halt
 * opens the typed-confirm HALT PLATFORM modal; releasing prompts for an MFA code
 * inline (no confirm phrase needed to release).
 */
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { HaltPlatformModalComponent } from './halt-platform-modal.component';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';

@Component({
  selector: 'app-admin-overview',
  standalone: true,
  imports: [
    RouterLink, TranslateModule, HaltPlatformModalComponent,
    ImpersonationBannerComponent, TotpInputComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    @if (admin.platformHalted()) {
      <div class="bg-red-600 text-white px-4 py-3 text-sm font-semibold text-center" role="alert">
        {{ 'admin.overview.halt_banner' | translate }}
      </div>
    }

    <div class="mx-auto max-w-6xl p-6 space-y-8">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">{{ 'admin.overview.title' | translate }}</h1>
        <nav class="flex gap-3 text-sm">
          <a routerLink="/admin/users" class="text-blue-600 hover:underline">{{ 'admin.nav.users' | translate }}</a>
          <a routerLink="/admin/audit" class="text-blue-600 hover:underline">{{ 'admin.nav.audit' | translate }}</a>
          <a routerLink="/admin/flags" class="text-blue-600 hover:underline">{{ 'admin.nav.flags' | translate }}</a>
          <a routerLink="/admin/health" class="text-blue-600 hover:underline">{{ 'admin.nav.health' | translate }}</a>
        </nav>
      </div>

      @if (admin.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">
          {{ err.message }}
        </div>
      }

      <!-- ===== KPI cards ===== -->
      <section>
        <h2 class="text-lg font-semibold mb-3">{{ 'admin.overview.kpis' | translate }}</h2>
        @if (admin.health(); as h) {
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
              <div class="text-xs uppercase text-gray-500">{{ 'admin.health.queue_total' | translate }}</div>
              <div class="text-lg font-bold font-mono">{{ queueTotal(h.queue_depths) }}</div>
            </div>
            <div class="border rounded p-4">
              <div class="text-xs uppercase text-gray-500">{{ 'admin.health.sentiment_backlog' | translate }}</div>
              <div class="text-lg font-bold font-mono">{{ h.sentiment_backlog }}</div>
            </div>
          </div>
        } @else {
          <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
        }
      </section>

      <!-- ===== Kill-switch card ===== -->
      <section class="border rounded p-4">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-lg font-semibold">{{ 'admin.overview.killswitch' | translate }}</h2>
            <p class="text-sm" [class.text-red-700]="admin.platformHalted()" [class.text-green-700]="!admin.platformHalted()">
              {{ (admin.platformHalted() ? 'admin.overview.halted' : 'admin.overview.running') | translate }}
            </p>
            @if (admin.platform()?.note; as note) {
              <p class="text-xs text-gray-500 mt-1">{{ note }}</p>
            }
          </div>
          @if (admin.platformHalted()) {
            <button type="button" (click)="openRelease()"
                    class="bg-green-600 text-white font-semibold px-4 py-2 rounded hover:bg-green-700">
              {{ 'admin.overview.release' | translate }}
            </button>
          } @else {
            <button type="button" (click)="haltOpen.set(true)"
                    class="bg-red-600 text-white font-semibold px-4 py-2 rounded hover:bg-red-700">
              {{ 'admin.halt.engage' | translate }}
            </button>
          }
        </div>

        <!-- Inline release (MFA only; no confirm phrase) -->
        @if (releaseOpen()) {
          <div class="mt-4 border-t pt-4 space-y-3">
            <label class="block text-xs font-semibold text-gray-700 uppercase">
              {{ 'admin.halt.mfa_label' | translate }}
            </label>
            <app-totp-input (codeChange)="releaseMfa.set($event)" [disabled]="releasing()" />
            @if (releaseError(); as err) {
              <p class="text-sm text-red-700">
                @if (err.code === 'MFA_REQUIRED') {
                  {{ 'admin.halt.error.MFA_REQUIRED' | translate }}
                } @else {
                  {{ err.message }}
                }
              </p>
            }
            <div class="flex gap-3 justify-end">
              <button type="button" (click)="cancelRelease()" class="px-3 py-1 rounded border text-sm hover:bg-gray-50">
                {{ 'common.cancel' | translate }}
              </button>
              <button type="button" (click)="release()" [disabled]="releaseMfa().length !== 6 || releasing()"
                      class="bg-green-600 text-white px-3 py-1 rounded text-sm hover:bg-green-700 disabled:opacity-40">
                {{ (releasing() ? 'admin.overview.releasing' : 'admin.overview.release') | translate }}
              </button>
            </div>
          </div>
        }
      </section>
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
