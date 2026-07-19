import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { GoogleButtonComponent } from '../google-button/google-button.component';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { BlueprintDirective } from '../../shared/ui/blueprint.directive';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, RouterLink, TranslateModule,
    GoogleButtonComponent, ButtonComponent, CardComponent, BlueprintDirective,
  ],
  template: `
    <div class="flex justify-center px-6 py-12">
      <div class="flex w-full max-w-[400px] flex-col gap-6">
        <div class="flex flex-col items-center gap-3">
          <span stpBlueprint aria-hidden="true"
                class="inline-flex h-12 w-12 items-end justify-center gap-1 bg-transparent p-[10px] pb-2">
            <span class="h-3 w-[5px] bg-accent"></span>
            <span class="h-[21px] w-[5px] bg-accent"></span>
            <span class="h-2 w-[5px] bg-accent-400"></span>
          </span>
          <h1 class="m-0 font-heading text-2xl font-semibold text-ink">{{ 'auth.login.title' | translate }}</h1>
        </div>

        @if (facade.error(); as err) {
          <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
            {{ 'auth.login.error.' + err.code | translate }}
          </div>
        }

        <app-card>
          <app-google-button />

          <form [formGroup]="form" (ngSubmit)="onSubmit()">
            <div class="mb-4">
              <label for="email" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.login.email' | translate }}</label>
              <input id="email" type="email" formControlName="email" autocomplete="email"
                     [attr.aria-invalid]="isInvalid('email')"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
              @if (isInvalid('email')) {
                <p class="mt-1 text-xs text-down-deep" role="alert">
                  @if (form.controls.email.errors?.['required']) {
                    {{ 'auth.login.errors.email_required' | translate }}
                  } @else {
                    {{ 'auth.login.errors.email_invalid' | translate }}
                  }
                </p>
              }
            </div>

            <div class="mb-4">
              <label for="password" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.login.password' | translate }}</label>
              <input id="password" type="password" formControlName="password" autocomplete="current-password"
                     [attr.aria-invalid]="isInvalid('password')"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
              @if (isInvalid('password')) {
                <p class="mt-1 text-xs text-down-deep" role="alert">
                  {{ 'auth.login.errors.password_required' | translate }}
                </p>
              }
            </div>

            <app-button type="submit" variant="primary" [frame]="true"
                        class="block [&>button]:w-full"
                        [disabled]="form.invalid || facade.status() === 'loading'"
                        [loading]="facade.status() === 'loading'">
              {{ 'auth.login.submit' | translate }}
            </app-button>
          </form>
        </app-card>

        <div class="flex flex-col items-center gap-2 text-center text-[13px]">
          <p class="m-0"><a routerLink="/password-reset" class="text-accent-700 hover:underline">{{ 'auth.login.forgot' | translate }}</a></p>
          <p class="m-0 text-neutral-600">{{ 'auth.login.no_account' | translate }} <a routerLink="/register" class="text-accent-700 hover:underline">{{ 'auth.login.register_link' | translate }}</a></p>
        </div>
      </div>
    </div>
  `,
})
export class LoginComponent {
  facade = inject(AuthFacade);
  private fb = inject(FormBuilder);

  form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
  });

  constructor() {
    // Defensive reset: if we landed on /login with a stale `'loading'`
    // status from a prior screen (register → /resend-verification → back,
    // or startGoogleSignIn that didn't actually navigate), the submit
    // button would otherwise stay disabled. setIdle is a no-op for authed
    // and mfa_pending states so we don't disturb real sessions.
    this.facade.resetFormState();
  }

  /** Show a field's error only once the user has interacted with it. */
  isInvalid(name: 'email' | 'password'): boolean {
    const c = this.form.controls[name];
    return c.invalid && (c.dirty || c.touched);
  }

  async onSubmit(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const { email, password } = this.form.getRawValue();
    await this.facade.login(email, password);
  }
}
