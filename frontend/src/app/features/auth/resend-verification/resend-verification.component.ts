import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';

@Component({
  selector: 'app-resend-verification',
  standalone: true,
  imports: [CommonModule, RouterLink, TranslateModule, ButtonComponent, CardComponent],
  template: `
    <div class="flex justify-center px-6 py-12">
      <div class="flex w-full max-w-[400px] flex-col gap-6 text-center">
        <div class="flex flex-col items-center gap-3">
          <h1 class="m-0 font-heading text-2xl font-semibold text-ink">{{ 'auth.resend.title' | translate }}</h1>
          <p class="m-0 text-sm text-neutral-600">{{ 'auth.resend.description' | translate }}</p>
        </div>

        <app-card>
          @if (sent()) {
            <p class="mb-4 mt-0 bg-accent-100 px-4 py-3 text-sm text-accent-800">{{ 'auth.resend.sent' | translate }}</p>
          }

          @if (!hasEmailParam) {
            <div class="mb-4 text-left">
              <label for="resend-email" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.resend.email' | translate }}</label>
              <input id="resend-email" type="email" autocomplete="email" [value]="email()"
                     (input)="onEmailInput($event)"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
            </div>
          }

          @if (error(); as msg) {
            <p role="alert" class="mb-4 mt-0 text-sm text-down-deep">{{ msg | translate }}</p>
          }

          <app-button variant="primary" [frame]="true"
                      class="block [&>button]:w-full"
                      [disabled]="sending()"
                      [loading]="sending()"
                      (clicked)="resend()">
            {{ 'auth.resend.submit' | translate }}
          </app-button>
        </app-card>

        <p class="m-0 text-[13px]">
          <a routerLink="/login" class="text-accent-700 hover:underline">{{ 'auth.resend.back_to_login' | translate }}</a>
        </p>
      </div>
    </div>
  `,
})
export class ResendVerificationComponent {
  private facade = inject(AuthFacade);
  private route = inject(ActivatedRoute);

  private readonly paramEmail = this.route.snapshot.queryParamMap.get('email') || '';
  readonly hasEmailParam = !!this.paramEmail;

  email = signal(this.paramEmail);
  sent = signal(false);
  sending = signal(false);
  /** Translation key for the current error, or null. */
  error = signal<string | null>(null);

  onEmailInput(ev: Event): void {
    this.email.set((ev.target as HTMLInputElement).value);
  }

  async resend(): Promise<void> {
    const email = this.email().trim();
    if (!email) {
      this.error.set('auth.resend.need_email');
      return;
    }
    this.error.set(null);
    this.sending.set(true);
    const ok = await this.facade.resendVerification(email);
    this.sending.set(false);
    if (ok) {
      this.sent.set(true);
    } else {
      this.error.set('auth.resend.error');
    }
  }
}
