/**
 * /oauth/callback — landing page after Google → backend → frontend round-trip.
 *
 * URL shape: /oauth/callback?exchange=<one-time-code>  (success)
 *         OR /oauth/callback?error=oauth_failed       (allauth callback failed)
 *
 * On success: POST exchange code to backend, route to /dashboard (no MFA) or
 * /login/mfa (MFA enrolled) based on the response. On error: show a friendly
 * message + a "Back to sign in" link.
 *
 * The exchange code is single-use and 5-minute lifetime, so re-loading this
 * page after a successful exchange will show an error — which is the right
 * behavior (no token replay).
 */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

@Component({
  selector: 'app-oauth-callback',
  standalone: true,
  imports: [CommonModule, RouterLink, TranslateModule],
  template: `
    <div class="mx-auto max-w-[400px] px-6 py-12 text-center">
      @if (state() === 'working') {
        <h1 class="mb-4 font-heading text-2xl font-semibold text-ink">{{ 'oauth.callback.working_title' | translate }}</h1>
        <p class="text-sm text-neutral-700">{{ 'oauth.callback.working_body' | translate }}</p>
        <div class="mt-6 inline-block h-8 w-8 animate-spin rounded-full border-4 border-accent border-t-transparent" role="status"></div>
      } @else if (state() === 'error') {
        <div class="mb-4 rounded-none border border-down bg-down-tint px-4 py-6 text-down-deep">
          <h1 class="mb-2 font-heading text-xl font-semibold">{{ 'oauth.callback.error_title' | translate }}</h1>
          <p class="text-sm">
            {{ 'oauth.callback.error.' + (errorCode() ?? 'UNKNOWN') | translate : { default: errorMessage() } }}
          </p>
        </div>
        <a routerLink="/login"
           class="inline-flex items-center justify-center rounded-none bg-accent-700 px-4 py-2 font-heading text-sm font-semibold text-bg transition-colors hover:bg-accent-800">
          {{ 'oauth.callback.back_to_login' | translate }}
        </a>
      }
    </div>
  `,
})
export class OAuthCallbackComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private facade = inject(AuthFacade);

  state = signal<'working' | 'error'>('working');
  errorCode = signal<string | null>(null);
  errorMessage = signal<string>('Sign-in failed. Please try again.');

  async ngOnInit(): Promise<void> {
    const params = this.route.snapshot.queryParamMap;
    const error = params.get('error');
    const exchange = params.get('exchange');

    if (error) {
      this.state.set('error');
      this.errorCode.set(error.toUpperCase());
      return;
    }
    if (!exchange) {
      this.state.set('error');
      this.errorCode.set('NO_EXCHANGE_CODE');
      return;
    }

    const ok = await this.facade.completeGoogleSignIn(exchange);
    if (!ok) {
      this.state.set('error');
      const err = this.facade.error();
      if (err) {
        this.errorCode.set(err.code);
        this.errorMessage.set(err.message);
      }
    }
    // On success, completeGoogleSignIn already navigated to /dashboard or /login/mfa.
  }
}
