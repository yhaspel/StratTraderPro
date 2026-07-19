/**
 * /settings/security — single page housing four sub-cards ("Industry" system):
 *   1. MFA status (enroll button OR disable form)
 *   2. Backup codes (regenerate)
 *   3. Sessions list with revoke
 *   4. Password change
 */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { MfaFacade } from '../../../abstraction/facades/mfa.facade';
import { ProfileFacade } from '../../../abstraction/facades/profile.facade';
import { SessionsFacade } from '../../../abstraction/facades/sessions.facade';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { StatusChipComponent } from '../../shared/ui/status-chip.component';

@Component({
  selector: 'app-security',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterLink,
    TranslateModule,
    DatePipe,
    ButtonComponent,
    CardComponent,
    PageHeaderComponent,
    StatusChipComponent,
  ],
  template: `
    <div class="mx-auto max-w-3xl p-6">
      <app-page-header [heading]="'security.title' | translate" />

      <div class="flex flex-col gap-s6">
        <!-- ========== MFA card ========== -->
        <app-card>
          <div class="mb-s3 flex items-start justify-between gap-3">
            <div>
              <h2 class="m-0 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
                {{ 'security.mfa.title' | translate }}
              </h2>
              <p class="mt-0.5 text-sm text-neutral-600">{{ 'security.mfa.subtitle' | translate }}</p>
            </div>
            @if (auth.user()?.mfa_enabled) {
              <app-status-chip tone="up" class="shrink-0">
                ✓ {{ 'security.mfa.enabled' | translate }}
              </app-status-chip>
            } @else {
              <app-status-chip tone="neutral" class="shrink-0">
                {{ 'security.mfa.disabled' | translate }}
              </app-status-chip>
            }
          </div>

          @if (!auth.user()?.mfa_enabled) {
            <a routerLink="/settings/security/mfa/setup"
               class="inline-flex items-center justify-center rounded-none border border-accent bg-accent px-3 py-1.5 font-heading text-sm font-semibold leading-tight text-bg transition-colors hover:bg-accent-600">
              {{ 'security.mfa.enroll_cta' | translate }}
            </a>
          } @else {
            <form [formGroup]="disableForm" (ngSubmit)="onDisable()" class="space-y-3">
              <p class="text-sm text-neutral-700">{{ 'security.mfa.disable_help' | translate }}</p>
              <input
                type="password"
                formControlName="password"
                autocomplete="current-password"
                aria-label="Current password"
                [placeholder]="'security.mfa.password_placeholder' | translate"
                class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none"
              />
              <input
                type="text"
                inputmode="numeric"
                formControlName="code"
                autocomplete="one-time-code"
                maxlength="6"
                aria-label="Authenticator code"
                [placeholder]="'security.mfa.totp_placeholder' | translate"
                class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none"
              />
              <app-button
                type="submit"
                variant="danger"
                [disabled]="disableForm.invalid || mfa.loading()"
              >
                {{ 'security.mfa.disable_cta' | translate }}
              </app-button>
            </form>
          }
          @if (mfa.error(); as err) {
            <p role="alert" class="mt-3 text-sm text-down-deep">{{ err.message }}</p>
          }
        </app-card>

        <!-- ========== Backup codes (only when MFA enabled) ========== -->
        @if (auth.user()?.mfa_enabled) {
          <app-card>
            <h2 class="m-0 mb-1 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
              {{ 'security.backup.title' | translate }}
            </h2>
            <p class="mb-s3 text-sm text-neutral-600">{{ 'security.backup.subtitle' | translate }}</p>
            <form [formGroup]="regenForm" (ngSubmit)="onRegenerate()" class="space-y-3">
              <input
                type="password"
                formControlName="password"
                autocomplete="current-password"
                aria-label="Current password"
                [placeholder]="'security.mfa.password_placeholder' | translate"
                class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none"
              />
              <input
                type="text"
                inputmode="numeric"
                formControlName="code"
                autocomplete="one-time-code"
                maxlength="6"
                aria-label="Authenticator code"
                [placeholder]="'security.mfa.totp_placeholder' | translate"
                class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none"
              />
              <app-button
                type="submit"
                variant="secondary"
                [disabled]="regenForm.invalid || mfa.loading()"
              >
                {{ 'security.backup.regenerate_cta' | translate }}
              </app-button>
            </form>
            @if (mfa.backupCodes(); as codes) {
              <div class="mt-s3 rounded-none border border-warn bg-warn-tint p-3">
                <p class="mb-2 text-sm text-warn-deep">⚠ {{ 'security.backup.shown_once' | translate }}</p>
                <ul class="grid grid-cols-2 gap-2 font-mono text-sm">
                  @for (c of codes; track c) {
                    <li class="rounded-none border border-divider bg-bg px-2 py-1">{{ c }}</li>
                  }
                </ul>
              </div>
            }
            @if (mfa.error(); as err) {
              <p role="alert" class="mt-3 text-sm text-down-deep">{{ err.message }}</p>
            }
          </app-card>
        }

        <!-- ========== Sessions card ========== -->
        <app-card>
          <div class="mb-s3 flex items-center justify-between gap-3">
            <div>
              <h2 class="m-0 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
                {{ 'security.sessions.title' | translate }}
              </h2>
              <p class="mt-0.5 text-sm text-neutral-600">{{ 'security.sessions.subtitle' | translate }}</p>
            </div>
            <app-button
              variant="ghost"
              class="shrink-0"
              [disabled]="sessions.loading()"
              (clicked)="onRevokeAll()"
            >
              <span class="text-down">{{ 'security.sessions.revoke_all' | translate }}</span>
            </app-button>
          </div>
          @if (sessions.error(); as err) {
            <p role="alert" class="mb-3 text-sm text-down-deep">{{ err.message }}</p>
          }
          @if (sessions.loading()) {
            <p class="text-sm text-neutral-600">{{ 'common.loading' | translate }}</p>
          } @else if (sessions.sessions().length === 0) {
            <p class="text-sm text-neutral-600">{{ 'security.sessions.empty' | translate }}</p>
          } @else {
            <ul class="divide-y divide-divider">
              @for (s of sessions.sessions(); track s.family_id) {
                <li class="flex items-center justify-between gap-3 py-3">
                  <div>
                    <p class="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
                      {{ s.device }}
                      @if (s.current) {
                        <app-status-chip tone="info">
                          {{ 'security.sessions.current' | translate }}
                        </app-status-chip>
                      }
                    </p>
                    <p class="mt-0.5 font-mono text-xs text-neutral-600">
                      {{ 'security.sessions.last_used' | translate }}:
                      {{ s.last_used_at ? (s.last_used_at | date:'medium') : '—' }}
                      · IP {{ s.ip_masked || '—' }}
                    </p>
                  </div>
                  @if (!s.current) {
                    <app-button variant="ghost" class="shrink-0" (clicked)="onRevokeOne(s.family_id)">
                      <span class="text-down">{{ 'security.sessions.revoke_one' | translate }}</span>
                    </app-button>
                  }
                </li>
              }
            </ul>
          }
        </app-card>

        <!-- ========== Password change card ========== -->
        <app-card>
          <h2 class="m-0 mb-1 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
            {{ 'security.password.title' | translate }}
          </h2>
          <p class="mb-s3 text-sm text-neutral-600">{{ 'security.password.subtitle' | translate }}</p>
          <form [formGroup]="passwordForm" (ngSubmit)="onChangePassword()" class="max-w-md space-y-3">
            <input
              type="password"
              formControlName="current"
              autocomplete="current-password"
              aria-label="Current password"
              [placeholder]="'security.password.current' | translate"
              class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none"
            />
            <input
              type="password"
              formControlName="next"
              autocomplete="new-password"
              aria-label="New password"
              [placeholder]="'security.password.next' | translate"
              class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none"
            />
            <p class="text-[11px] text-neutral-600">{{ 'auth.register.password_hint' | translate }}</p>
            <app-button
              type="submit"
              variant="primary"
              [disabled]="passwordForm.invalid || profile.loading()"
            >
              {{ 'security.password.cta' | translate }}
            </app-button>
          </form>
          @if (passwordSuccess()) {
            <p class="mt-3 text-sm text-accent-700">✓ {{ 'security.password.success' | translate }}</p>
          }
          @if (profile.error(); as err) {
            <p class="mt-3 text-sm text-down-deep">{{ err.message }}</p>
          }
        </app-card>
      </div>
    </div>
  `,
})
export class SecurityComponent implements OnInit {
  auth = inject(AuthFacade);
  mfa = inject(MfaFacade);
  profile = inject(ProfileFacade);
  sessions = inject(SessionsFacade);
  private fb = inject(FormBuilder);

  passwordSuccess = signal(false);

  disableForm = this.fb.nonNullable.group({
    password: ['', Validators.required],
    code: ['', [Validators.required, Validators.minLength(6), Validators.maxLength(6)]],
  });

  regenForm = this.fb.nonNullable.group({
    password: ['', Validators.required],
    code: ['', [Validators.required, Validators.minLength(6), Validators.maxLength(6)]],
  });

  passwordForm = this.fb.nonNullable.group({
    current: ['', Validators.required],
    next: ['', [Validators.required, Validators.minLength(12)]],
  });

  async ngOnInit(): Promise<void> {
    await Promise.all([this.profile.load(), this.sessions.load()]);
  }

  async onDisable(): Promise<void> {
    if (this.disableForm.invalid) return;
    const { password, code } = this.disableForm.getRawValue();
    const ok = await this.mfa.disable(password, code);
    if (ok) this.disableForm.reset();
  }

  async onRegenerate(): Promise<void> {
    if (this.regenForm.invalid) return;
    const { password, code } = this.regenForm.getRawValue();
    const ok = await this.mfa.regenerateBackupCodes(password, code);
    if (ok) this.regenForm.reset();
  }

  async onRevokeOne(familyId: string): Promise<void> {
    await this.sessions.revoke(familyId);
  }

  async onRevokeAll(): Promise<void> {
    await this.sessions.revokeAllOthers();
  }

  async onChangePassword(): Promise<void> {
    if (this.passwordForm.invalid) return;
    this.passwordSuccess.set(false);
    const { current, next } = this.passwordForm.getRawValue();
    const ok = await this.profile.changePassword(current, next);
    if (ok) {
      this.passwordSuccess.set(true);
      this.passwordForm.reset();
      // Refresh sessions list to show others were revoked.
      await this.sessions.load();
    }
  }
}
