import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

@Component({
  selector: 'app-resend-verification',
  standalone: true,
  imports: [CommonModule, RouterLink, TranslateModule],
  template: `
    <div class="mx-auto max-w-md p-6 text-center">
      <h1 class="text-2xl font-bold mb-4">{{ 'auth.resend.title' | translate }}</h1>
      <p class="mb-6 text-gray-600">{{ 'auth.resend.description' | translate }}</p>

      @if (sent()) {
        <p class="text-green-600 mb-4">{{ 'auth.resend.sent' | translate }}</p>
      }

      @if (!hasEmailParam) {
        <div class="mb-4 text-left">
          <label for="resend-email" class="block text-sm font-medium mb-1">{{ 'auth.resend.email' | translate }}</label>
          <input id="resend-email" type="email" autocomplete="email" [value]="email()"
                 (input)="onEmailInput($event)"
                 class="w-full border rounded px-3 py-2" />
        </div>
      }

      @if (error(); as msg) {
        <p role="alert" class="text-red-600 mb-4">{{ msg | translate }}</p>
      }

      <button (click)="resend()" [disabled]="sending()"
              class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50">
        {{ 'auth.resend.submit' | translate }}
      </button>

      <p class="mt-4 text-sm">
        <a routerLink="/login" class="text-blue-600 hover:underline">{{ 'auth.resend.back_to_login' | translate }}</a>
      </p>
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
