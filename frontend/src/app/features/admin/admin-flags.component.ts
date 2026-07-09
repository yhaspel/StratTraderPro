/** /admin/flags — feature-flag registry with guarded toggles (M10).
 *
 * Toggling any flag opens an inline MFA prompt. `dangerous` flags additionally
 * require typing the flag's exact name to confirm. `immutable` flags (mutable =
 * false) are rendered read-only — their toggle is disabled and no MFA prompt can
 * be opened for them.
 */
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { FeatureFlag } from '../../core/models/admin.models';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';

@Component({
  selector: 'app-admin-flags',
  standalone: true,
  imports: [RouterLink, TranslateModule, ImpersonationBannerComponent, TotpInputComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-4xl p-6 space-y-6">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">{{ 'admin.flags.title' | translate }}</h1>
        <a routerLink="/admin" class="text-sm text-blue-600 hover:underline">{{ 'admin.nav.back' | translate }}</a>
      </div>

      @if (admin.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">{{ err.message }}</div>
      }

      @if (admin.loading()) {
        <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
      } @else if (admin.flags().length === 0) {
        <p class="text-sm text-gray-500">{{ 'admin.flags.empty' | translate }}</p>
      } @else {
        <ul class="divide-y border rounded">
          @for (f of admin.flags(); track f.name) {
            <li class="px-4 py-3">
              <div class="flex items-start justify-between gap-4">
                <div>
                  <div class="flex items-center gap-2">
                    <span class="font-mono font-semibold text-sm">{{ f.name }}</span>
                    @if (f.dangerous) {
                      <span class="text-xs bg-red-100 text-red-700 rounded px-1.5 py-0.5">{{ 'admin.flags.dangerous' | translate }}</span>
                    }
                    @if (!f.mutable) {
                      <span class="text-xs bg-gray-200 text-gray-600 rounded px-1.5 py-0.5">{{ 'admin.flags.immutable' | translate }}</span>
                    }
                  </div>
                  <p class="text-xs text-gray-500 mt-1">{{ f.description }}</p>
                  <p class="text-xs text-gray-400 mt-0.5">{{ 'admin.flags.source' | translate }}: {{ f.source }}</p>
                </div>
                <div class="text-right">
                  <span class="text-sm font-semibold" [class.text-green-700]="f.enabled" [class.text-gray-500]="!f.enabled">
                    {{ (f.enabled ? 'admin.flags.on' : 'admin.flags.off') | translate }}
                  </span>
                  <div class="mt-2">
                    <button type="button" (click)="open(f)" [disabled]="!f.mutable"
                            class="text-sm px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50">
                      {{ (f.enabled ? 'admin.flags.disable' : 'admin.flags.enable') | translate }}
                    </button>
                  </div>
                </div>
              </div>

              <!-- Inline MFA + (dangerous) name-confirm prompt -->
              @if (openFlag() === f.name) {
                <div class="mt-3 border-t pt-3 space-y-3">
                  @if (f.dangerous) {
                    <div>
                      <label [attr.for]="'flag-confirm-' + f.name" class="block text-xs font-semibold text-gray-700 uppercase mb-1">
                        {{ 'admin.flags.confirm_name' | translate }}
                      </label>
                      <input [id]="'flag-confirm-' + f.name" type="text" [value]="nameConfirm()"
                             (input)="nameConfirm.set($any($event.target).value)" autocomplete="off" spellcheck="false"
                             class="w-full font-mono text-sm border-2 rounded px-3 py-2"
                             [class.border-green-400]="nameConfirm() === f.name" />
                    </div>
                  }
                  <label class="block text-xs font-semibold text-gray-700 uppercase">{{ 'admin.flags.mfa' | translate }}</label>
                  <app-totp-input (codeChange)="mfaCode.set($event)" [disabled]="submitting()" />
                  @if (toggleError(); as err) {
                    <p class="text-sm text-red-700">
                      @if (knownError(err.code)) {
                        {{ ('admin.flags.error.' + err.code) | translate }}
                      } @else {
                        {{ err.message }}
                      }
                    </p>
                  }
                  <div class="flex gap-3 justify-end">
                    <button type="button" (click)="cancel()" class="px-3 py-1 rounded border text-sm hover:bg-gray-50">
                      {{ 'common.cancel' | translate }}
                    </button>
                    <button type="button" (click)="submit(f)" [disabled]="!canSubmit(f)"
                            class="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700 disabled:opacity-40">
                      {{ (submitting() ? 'admin.flags.submitting' : 'common.confirm') | translate }}
                    </button>
                  </div>
                </div>
              }
            </li>
          }
        </ul>
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
