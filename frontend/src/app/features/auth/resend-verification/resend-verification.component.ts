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

  sent = signal(false);
  sending = signal(false);

  async resend(): Promise<void> {
    const email = this.route.snapshot.queryParamMap.get('email') || '';
    if (!email) return;
    this.sending.set(true);
    const ok = await this.facade.resendVerification(email);
    this.sending.set(false);
    if (ok) this.sent.set(true);
  }
}
