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
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { BlueprintDirective } from '../../shared/ui/blueprint.directive';

@Component({
  selector: 'app-mfa-challenge',
  standalone: true,
  imports: [
    CommonModule, FormsModule, RouterLink, TranslateModule,
    TotpInputComponent, ButtonComponent, CardComponent, BlueprintDirective,
  ],
  template: `
    <div class="flex justify-center px-6 py-12">
      <div class="flex w-full max-w-[400px] flex-col gap-6">
        <div class="flex flex-col items-center gap-3 text-center">
          <span stpBlueprint aria-hidden="true"
                class="inline-flex h-12 w-12 items-end justify-center gap-1 bg-transparent p-[10px] pb-2">
            <span class="h-3 w-[5px] bg-accent"></span>
            <span class="h-[21px] w-[5px] bg-accent"></span>
            <span class="h-2 w-[5px] bg-accent-400"></span>
          </span>
          <h1 class="m-0 font-heading text-2xl font-semibold text-ink">{{ 'mfa.challenge.title' | translate }}</h1>
          <p class="m-0 text-sm text-neutral-600">{{ 'mfa.challenge.subtitle' | translate }}</p>
        </div>

        @if (facade.error(); as err) {
          <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
            {{ 'mfa.error.' + err.code | translate : { default: err.message } }}
          </div>
        }

        <app-card>
          @if (!useBackup()) {
            <app-totp-input
              #totp
              ariaLabel="Authentication code"
              (codeChange)="code.set($event)"
              (codeComplete)="onSubmit()"
            />
          } @else {
            <label class="mb-1 block text-xs font-medium text-neutral-700" for="backup">
              {{ 'mfa.challenge.backup_label' | translate }}
            </label>
            <input
              id="backup"
              type="text"
              [ngModel]="code()"
              (ngModelChange)="code.set($event)"
              autocomplete="one-time-code"
              placeholder="XXXX-XXXX"
              class="min-h-[44px] w-full rounded-none border border-divider bg-surface px-3 font-mono text-base uppercase tracking-[0.15em] text-ink focus:border-accent focus:outline-none"
            />
          }

          <app-button variant="primary" [frame]="true"
                      class="mt-[18px] block [&>button]:w-full"
                      [disabled]="!canSubmit()"
                      (clicked)="onSubmit()">
            {{ 'mfa.challenge.submit' | translate }}
          </app-button>

          <app-button variant="ghost"
                      class="mt-3 flex justify-center [&>button]:text-[13px]"
                      (clicked)="toggleMode()">
            {{ (useBackup()
                ? 'mfa.challenge.use_totp_instead'
                : 'mfa.challenge.use_backup_instead') | translate }}
          </app-button>
        </app-card>

        <div class="text-center text-[13px]">
          <a routerLink="/login" class="text-neutral-700 hover:underline" (click)="onCancel($event)">
            {{ 'mfa.challenge.cancel' | translate }}
          </a>
        </div>
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
