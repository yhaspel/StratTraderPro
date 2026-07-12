/**
 * /settings/security — single page housing four sub-cards:
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

@Component({
  selector: 'app-security',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslateModule, DatePipe],
  template: `
    <div class="mx-auto max-w-3xl p-6 space-y-8">
      <h1 class="text-2xl font-bold">{{ 'security.title' | translate }}</h1>

      <!-- ========== MFA card ========== -->
      <section class="border rounded-lg p-6">
        <div class="flex justify-between items-start mb-4">
          <div>
            <h2 class="text-lg font-semibold">{{ 'security.mfa.title' | translate }}</h2>
            <p class="text-sm text-gray-600">{{ 'security.mfa.subtitle' | translate }}</p>
          </div>
          @if (auth.user()?.mfa_enabled) {
            <span class="inline-block px-2 py-1 bg-green-100 text-green-800 text-xs rounded">
              ✓ {{ 'security.mfa.enabled' | translate }}
            </span>
          } @else {
            <span class="inline-block px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded">
              {{ 'security.mfa.disabled' | translate }}
            </span>
          }
        </div>

        @if (!auth.user()?.mfa_enabled) {
          <a routerLink="/settings/security/mfa/setup"
             class="inline-block bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">
            {{ 'security.mfa.enroll_cta' | translate }}
          </a>
        } @else {
          <form [formGroup]="disableForm" (ngSubmit)="onDisable()" class="space-y-3">
            <p class="text-sm text-gray-700">{{ 'security.mfa.disable_help' | translate }}</p>
            <input
              type="password"
              formControlName="password"
              autocomplete="current-password"
              [placeholder]="'security.mfa.password_placeholder' | translate"
              class="w-full border rounded px-3 py-2"
            />
            <input
              type="text"
              inputmode="numeric"
              formControlName="code"
              autocomplete="one-time-code"
              maxlength="6"
              [placeholder]="'security.mfa.totp_placeholder' | translate"
              class="w-full border rounded px-3 py-2 font-mono"
            />
            <button
              type="submit"
              [disabled]="disableForm.invalid || mfa.loading()"
              class="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-700 disabled:opacity-50"
            >
              {{ 'security.mfa.disable_cta' | translate }}
            </button>
          </form>
        }
        @if (mfa.error(); as err) {
          <p role="alert" class="mt-3 text-sm text-red-600">{{ err.message }}</p>
        }
      </section>

      <!-- ========== Backup codes (only when MFA enabled) ========== -->
      @if (auth.user()?.mfa_enabled) {
        <section class="border rounded-lg p-6">
          <h2 class="text-lg font-semibold mb-2">{{ 'security.backup.title' | translate }}</h2>
          <p class="text-sm text-gray-600 mb-4">{{ 'security.backup.subtitle' | translate }}</p>
          <form [formGroup]="regenForm" (ngSubmit)="onRegenerate()" class="space-y-3">
            <input
              type="password"
              formControlName="password"
              autocomplete="current-password"
              [placeholder]="'security.mfa.password_placeholder' | translate"
              class="w-full border rounded px-3 py-2"
            />
            <input
              type="text"
              inputmode="numeric"
              formControlName="code"
              autocomplete="one-time-code"
              maxlength="6"
              [placeholder]="'security.mfa.totp_placeholder' | translate"
              class="w-full border rounded px-3 py-2 font-mono"
            />
            <button
              type="submit"
              [disabled]="regenForm.invalid || mfa.loading()"
              class="border px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50"
            >
              {{ 'security.backup.regenerate_cta' | translate }}
            </button>
          </form>
          @if (mfa.backupCodes(); as codes) {
            <div class="mt-4 p-3 bg-amber-50 border border-amber-200 rounded">
              <p class="text-sm text-amber-800 mb-2">⚠ {{ 'security.backup.shown_once' | translate }}</p>
              <ul class="grid grid-cols-2 gap-2 font-mono text-sm">
                @for (c of codes; track c) { <li class="bg-white px-2 py-1 rounded">{{ c }}</li> }
              </ul>
            </div>
          }
          @if (mfa.error(); as err) {
            <p role="alert" class="mt-3 text-sm text-red-600">{{ err.message }}</p>
          }
        </section>
      }

      <!-- ========== Sessions card ========== -->
      <section class="border rounded-lg p-6">
        <div class="flex justify-between items-center mb-4">
          <div>
            <h2 class="text-lg font-semibold">{{ 'security.sessions.title' | translate }}</h2>
            <p class="text-sm text-gray-600">{{ 'security.sessions.subtitle' | translate }}</p>
          </div>
          <button
            type="button"
            class="text-sm text-red-600 hover:underline"
            (click)="onRevokeAll()"
            [disabled]="sessions.loading()"
          >
            {{ 'security.sessions.revoke_all' | translate }}
          </button>
        </div>
        @if (sessions.error(); as err) {
          <p role="alert" class="mb-3 text-sm text-red-600">{{ err.message }}</p>
        }
        @if (sessions.loading()) {
          <p class="text-gray-500">{{ 'common.loading' | translate }}</p>
        } @else if (sessions.sessions().length === 0) {
          <p class="text-gray-500">{{ 'security.sessions.empty' | translate }}</p>
        } @else {
          <ul class="divide-y">
            @for (s of sessions.sessions(); track s.family_id) {
              <li class="py-3 flex justify-between items-center">
                <div>
                  <p class="font-medium">
                    {{ s.device }}
                    @if (s.current) {
                      <span class="ml-2 text-xs px-2 py-0.5 bg-blue-100 text-blue-800 rounded">
                        {{ 'security.sessions.current' | translate }}
                      </span>
                    }
                  </p>
                  <p class="text-sm text-gray-500">
                    {{ 'security.sessions.last_used' | translate }}:
                    {{ s.last_used_at ? (s.last_used_at | date:'medium') : '—' }}
                    · IP {{ s.ip_masked || '—' }}
                  </p>
                </div>
                @if (!s.current) {
                  <button
                    type="button"
                    class="text-sm text-red-600 hover:underline"
                    (click)="onRevokeOne(s.family_id)"
                  >
                    {{ 'security.sessions.revoke_one' | translate }}
                  </button>
                }
              </li>
            }
          </ul>
        }
      </section>

      <!-- ========== Password change card ========== -->
      <section class="border rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-2">{{ 'security.password.title' | translate }}</h2>
        <p class="text-sm text-gray-600 mb-4">{{ 'security.password.subtitle' | translate }}</p>
        <form [formGroup]="passwordForm" (ngSubmit)="onChangePassword()" class="space-y-3 max-w-md">
          <input
            type="password"
            formControlName="current"
            autocomplete="current-password"
            [placeholder]="'security.password.current' | translate"
            class="w-full border rounded px-3 py-2"
          />
          <input
            type="password"
            formControlName="next"
            autocomplete="new-password"
            [placeholder]="'security.password.next' | translate"
            class="w-full border rounded px-3 py-2"
          />
          <p class="text-xs text-gray-500">{{ 'auth.register.password_hint' | translate }}</p>
          <button
            type="submit"
            class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            [disabled]="passwordForm.invalid || profile.loading()"
          >
            {{ 'security.password.cta' | translate }}
          </button>
        </form>
        @if (passwordSuccess()) {
          <p class="mt-3 text-sm text-green-700">✓ {{ 'security.password.success' | translate }}</p>
        }
        @if (profile.error(); as err) {
          <p class="mt-3 text-sm text-red-700">{{ err.message }}</p>
        }
      </section>
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
