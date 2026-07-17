import { Component, ElementRef, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { GoogleButtonComponent } from '../google-button/google-button.component';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslateModule, GoogleButtonComponent],
  template: `
    <div class="mx-auto max-w-md p-6">
      <h1 class="text-2xl font-bold mb-6">{{ 'auth.login.title' | translate }}</h1>

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ 'auth.login.error.' + err.code | translate }}
        </div>
      }

      <app-google-button />

      <form [formGroup]="form" (ngSubmit)="onSubmit()">
        <div class="mb-4">
          <label for="email" class="block text-sm font-medium mb-1">{{ 'auth.login.email' | translate }}</label>
          <input id="email" type="email" formControlName="email" autocomplete="email"
                 [attr.aria-invalid]="isInvalid('email')"
                 class="w-full border rounded px-3 py-2" />
          @if (isInvalid('email')) {
            <p class="text-xs text-red-600 mt-1" role="alert">
              @if (form.controls.email.errors?.['required']) {
                {{ 'auth.login.errors.email_required' | translate }}
              } @else {
                {{ 'auth.login.errors.email_invalid' | translate }}
              }
            </p>
          }
        </div>

        <div class="mb-4">
          <label for="password" class="block text-sm font-medium mb-1">{{ 'auth.login.password' | translate }}</label>
          <input id="password" type="password" formControlName="password" autocomplete="current-password"
                 [attr.aria-invalid]="isInvalid('password')"
                 class="w-full border rounded px-3 py-2" />
          @if (isInvalid('password')) {
            <p class="text-xs text-red-600 mt-1" role="alert">
              {{ 'auth.login.errors.password_required' | translate }}
            </p>
          }
        </div>

        <button type="submit" [disabled]="facade.status() === 'loading'"
                class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:opacity-50">
          {{ 'auth.login.submit' | translate }}
        </button>
      </form>

      <div class="mt-4 text-sm text-center space-y-2">
        <p><a routerLink="/password-reset" class="text-blue-600 hover:underline">{{ 'auth.login.forgot' | translate }}</a></p>
        <p>{{ 'auth.login.no_account' | translate }} <a routerLink="/register" class="text-blue-600 hover:underline">{{ 'auth.login.register_link' | translate }}</a></p>
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
      // P2-DESIGN-6: the button stays enabled so Enter/click always reaches here;
      // reveal the errors and move focus to the first invalid field.
      this.form.markAllAsTouched();
      this.focusFirstInvalid();
      return;
    }
    const { email, password } = this.form.getRawValue();
    await this.facade.login(email, password);
  }

  private host = inject(ElementRef) as ElementRef<HTMLElement>;

  private focusFirstInvalid(): void {
    (this.host.nativeElement.querySelector(
      'input.ng-invalid, select.ng-invalid, textarea.ng-invalid',
    ) as HTMLElement | null)?.focus();
  }
}
