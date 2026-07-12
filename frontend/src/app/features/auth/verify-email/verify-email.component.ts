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
    <div class="mx-auto max-w-md p-6 text-center">
      <h1 class="text-2xl font-bold mb-4">Verify email</h1>
      @if (facade.status() === 'loading') {
        <p>{{ 'auth.verify_email.verifying' | translate }}</p>
      }
      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ err.message }}
        </div>
        <a routerLink="/resend-verification" class="text-blue-600 hover:underline">
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
