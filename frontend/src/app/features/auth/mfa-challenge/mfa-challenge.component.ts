/**
 * /login/mfa — second factor after a successful password login when the
 * account has MFA enabled. Submits TOTP (or backup code) against the held
 * mfa_token in AuthStore.
 */
import { Component, ViewChild, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { TotpInputComponent } from '../totp-input/totp-input.component';

@Component({
  selector: 'app-mfa-challenge',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, TranslateModule, TotpInputComponent],
  template: `
    <div class="mx-auto max-w-md p-6">
      <h1 class="text-2xl font-bold mb-2">{{ 'mfa.challenge.title' | translate }}</h1>
      <p class="text-gray-600 mb-6">{{ 'mfa.challenge.subtitle' | translate }}</p>

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ 'mfa.error.' + err.code | translate : { default: err.message } }}
        </div>
      }

      @if (!useBackup()) {
        <app-totp-input
          #totp
          ariaLabel="Authentication code"
          (codeChange)="code.set($event)"
          (codeComplete)="onSubmit()"
        />
      } @else {
        <label class="block text-sm font-medium mb-1" for="backup">
          {{ 'mfa.challenge.backup_label' | translate }}
        </label>
        <input
          id="backup"
          type="text"
          [ngModel]="code()"
          (ngModelChange)="code.set($event)"
          autocomplete="one-time-code"
          placeholder="XXXX-XXXX"
          class="w-full border-2 rounded px-3 py-3 font-mono tracking-wider uppercase"
        />
      }

      <button
        type="button"
        class="mt-6 w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:opacity-50"
        [disabled]="!canSubmit()"
        (click)="onSubmit()"
      >
        {{ 'mfa.challenge.submit' | translate }}
      </button>

      <button
        type="button"
        class="mt-3 w-full text-sm text-blue-600 hover:underline"
        (click)="toggleMode()"
      >
        {{ (useBackup()
            ? 'mfa.challenge.use_totp_instead'
            : 'mfa.challenge.use_backup_instead') | translate }}
      </button>

      <div class="mt-6 text-center text-sm">
        <a routerLink="/login" class="text-gray-600 hover:underline" (click)="onCancel($event)">
          {{ 'mfa.challenge.cancel' | translate }}
        </a>
      </div>
    </div>
  `,
})
export class MfaChallengeComponent {
  facade = inject(AuthFacade);
  private router = inject(Router);

  code = signal('');
  useBackup = signal(false);

  @ViewChild('totp') totp?: TotpInputComponent;

  constructor() {
    // Bounce to /login if no mfa_token is held — e.g. user refreshed the page.
    if (!this.facade.mfaToken()) {
      void this.router.navigate(['/login']);
    }
  }

  canSubmit(): boolean {
    const c = this.code();
    if (this.useBackup()) {
      return c.replace(/[-\s]/g, '').length >= 6;
    }
    return c.length === 6;
  }

  toggleMode(): void {
    this.useBackup.update(v => !v);
    this.code.set('');
    queueMicrotask(() => this.totp?.clear());
  }

  async onSubmit(): Promise<void> {
    if (!this.canSubmit()) return;
    const ok = await this.facade.verifyMfa(this.code(), this.useBackup());
    if (!ok) {
      // Wipe the input so the user can retry cleanly.
      this.code.set('');
      this.totp?.clear();
    }
  }

  async onCancel(ev: Event): Promise<void> {
    ev.preventDefault();
    await this.facade.cancelMfa();
  }
}
