import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

@Component({
  selector: 'app-verify-email',
  standalone: true,
  imports: [CommonModule, RouterLink, TranslateModule],
  template: `
    <div class="mx-auto max-w-[400px] px-6 py-12 text-center">
      <h1 class="mb-4 font-heading text-2xl font-semibold text-ink">Verify email</h1>
      @if (facade.status() === 'loading') {
        <p class="text-sm text-neutral-600">{{ 'auth.verify_email.verifying' | translate }}</p>
      }
      @if (facade.error(); as err) {
        <div class="mb-4 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
          {{ err.message }}
        </div>
        <a routerLink="/resend-verification" class="text-[13px] text-accent-700 hover:underline">
          {{ 'auth.verify_email.resend' | translate }}
        </a>
      }
    </div>
  `,
})
export class VerifyEmailComponent implements OnInit {
  facade = inject(AuthFacade);
  private route = inject(ActivatedRoute);

  ngOnInit(): void {
    const token = this.route.snapshot.queryParamMap.get('token');
    if (token) {
      this.facade.verifyEmail(token);
    }
  }
}
