/** /admin/flags — feature-flag registry with guarded toggles (M10).
 *
 * Toggling any flag opens an inline MFA prompt. `dangerous` flags additionally
 * require typing the flag's exact name to confirm. `immutable` flags (mutable =
 * false) are rendered read-only — their toggle is disabled and no MFA prompt can
 * be opened for them.
 *
 * Industry styling: sub-nav with accent underline, blueprint card list, chips
 * for flag badges/state (no hand-rolled toggle existed — the Enable/Disable
 * button is kept, restyled as a secondary app-button), shared inline-confirm
 * grammar (input → confirm → secondary cancel).
 */
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { FeatureFlag } from '../../core/models/admin.models';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

@Component({
  selector: 'app-admin-flags',
  standalone: true,
  imports: [
    NgClass, RouterLink, RouterLinkActive, TranslateModule, ImpersonationBannerComponent,
    TotpInputComponent, ButtonComponent, CardComponent, PageHeaderComponent, StatusChipComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-4xl space-y-6 p-6">
      <app-page-header [heading]="'admin.flags.title' | translate">
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
        <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">{{ err.message }}</div>
      }

      @if (admin.loading()) {
        <p class="text-sm text-neutral-600">{{ 'common.loading' | translate }}</p>
      } @else if (admin.flags().length === 0) {
        <p class="text-sm text-neutral-600">{{ 'admin.flags.empty' | translate }}</p>
      } @else {
        <app-card>
          <ul class="divide-y divide-divider">
            @for (f of admin.flags(); track f.name) {
              <li class="px-3 py-3">
                <div class="flex items-start justify-between gap-4">
                  <div>
                    <div class="flex items-center gap-2">
                      <span class="font-mono text-sm font-semibold">{{ f.name }}</span>
                      @if (f.dangerous) {
                        <app-status-chip tone="down">{{ 'admin.flags.dangerous' | translate }}</app-status-chip>
                      }
                      @if (!f.mutable) {
                        <app-status-chip tone="neutral">{{ 'admin.flags.immutable' | translate }}</app-status-chip>
                      }
                    </div>
                    <p class="mt-1 text-xs text-neutral-600">{{ f.description }}</p>
                    <p class="mt-0.5 text-xs text-neutral-600">{{ 'admin.flags.source' | translate }}: {{ f.source }}</p>
                  </div>
                  <div class="text-right">
                    <app-status-chip [tone]="f.enabled ? 'info' : 'neutral'">
                      {{ (f.enabled ? 'admin.flags.on' : 'admin.flags.off') | translate }}
                    </app-status-chip>
                    <div class="mt-2">
                      <app-button variant="secondary" (clicked)="open(f)" [disabled]="!f.mutable">
                        {{ (f.enabled ? 'admin.flags.disable' : 'admin.flags.enable') | translate }}
                      </app-button>
                    </div>
                  </div>
                </div>

                <!-- Inline MFA + (dangerous) name-confirm prompt -->
                @if (openFlag() === f.name) {
                  <div class="mt-3 space-y-3 border-t border-divider pt-3">
                    @if (f.dangerous) {
                      <div>
                        <label [attr.for]="'flag-confirm-' + f.name" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">
                          {{ 'admin.flags.confirm_name' | translate }}
                        </label>
                        <input [id]="'flag-confirm-' + f.name" type="text" [value]="nameConfirm()"
                               (input)="nameConfirm.set($any($event.target).value)" autocomplete="off" spellcheck="false"
                               class="w-full rounded-none border-2 bg-surface px-3 py-2 font-mono text-sm text-ink"
                               [ngClass]="nameConfirm() === f.name ? 'border-up' : 'border-divider'" />
                      </div>
                    }
                    <span class="block text-[11px] font-semibold uppercase tracking-wide text-accent-700">{{ 'admin.flags.mfa' | translate }}</span>
                    <app-totp-input [ariaLabel]="'MFA code'" (codeChange)="mfaCode.set($event)" [disabled]="submitting()" />
                    @if (toggleError(); as err) {
                      <p class="text-sm text-down">
                        @if (knownError(err.code)) {
                          {{ ('admin.flags.error.' + err.code) | translate }}
                        } @else {
                          {{ err.message }}
                        }
                      </p>
                    }
                    <div class="flex justify-end gap-3">
                      <app-button variant="primary" (clicked)="submit(f)" [disabled]="!canSubmit(f)" [loading]="submitting()">
                        {{ (submitting() ? 'admin.flags.submitting' : 'common.confirm') | translate }}
                      </app-button>
                      <app-button variant="secondary" (clicked)="cancel()">
                        {{ 'common.cancel' | translate }}
                      </app-button>
                    </div>
                  </div>
                }
              </li>
            }
          </ul>
        </app-card>
      }
    </div>
  `,
})
export class AdminFlagsComponent implements OnInit {
  admin = inject(AdminFacade);

  openFlag = signal<string | null>(null);
  mfaCode = signal('');
  nameConfirm = signal('');
  submitting = signal(false);
  toggleError = signal<ApiError | null>(null);

  ngOnInit(): void {
    void this.admin.loadFlags();
  }

  open(flag: FeatureFlag): void {
    if (!flag.mutable) { return; }
    this.openFlag.set(flag.name);
    this.mfaCode.set('');
    this.nameConfirm.set('');
    this.toggleError.set(null);
  }

  cancel(): void {
    this.openFlag.set(null);
  }

  canSubmit(flag: FeatureFlag): boolean {
    if (this.submitting() || this.mfaCode().length !== 6) { return false; }
    if (flag.dangerous && this.nameConfirm() !== flag.name) { return false; }
    return true;
  }

  async submit(flag: FeatureFlag): Promise<void> {
    if (!this.canSubmit(flag)) { return; }
    this.toggleError.set(null);
    this.submitting.set(true);
    try {
      const res = await this.admin.toggleFlag(flag.name, {
        enabled: !flag.enabled,
        mfa_code: this.mfaCode(),
      });
      if (res.ok) {
        this.openFlag.set(null);
      } else {
        this.toggleError.set(res.error);
      }
    } finally {
      this.submitting.set(false);
    }
  }

  knownError(code: string): boolean {
    return code === 'FLAG_IMMUTABLE' || code === 'MFA_REQUIRED';
  }
}
