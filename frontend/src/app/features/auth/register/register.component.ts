import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AbstractControl, ReactiveFormsModule, FormBuilder, ValidationErrors, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { GoogleButtonComponent } from '../google-button/google-button.component';

/** Client mirror of the backend LettersAndDigitsValidator (AC-01-9) so the
 * hint ("letters and digits") and the button's enabled state agree. Uses
 * Unicode property escapes (\p{L} / \p{Nd}) to match Python str.isalpha() /
 * str.isdigit() — an ASCII-only mirror would wrongly reject a valid non-Latin
 * password (e.g. Cyrillic/CJK letters + a digit) and re-create the disabled-
 * button bug for those users. */
function lettersAndDigitsValidator(control: AbstractControl): ValidationErrors | null {
  const v = (control.value as string) ?? '';
  if (!v) { return null; } // 'required' covers the empty case
  return /\p{L}/u.test(v) && /\p{Nd}/u.test(v) ? null : { lettersAndDigits: true };
}

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslateModule, GoogleButtonComponent],
  template: `
    <div class="mx-auto max-w-md p-6">
      <h1 class="text-2xl font-bold mb-6">{{ 'auth.register.title' | translate }}</h1>

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ err.message }}
        </div>
      }

      <app-google-button />

      <form [formGroup]="form" (ngSubmit)="onSubmit()">
        <div class="mb-4">
          <label for="email" class="block text-sm font-medium mb-1">{{ 'auth.register.email' | translate }}</label>
          <input id="email" type="email" formControlName="email" autocomplete="email"
                 [attr.aria-invalid]="isInvalid('email')"
                 class="w-full border rounded px-3 py-2" />
          @if (isInvalid('email')) {
            <p class="text-xs text-red-600 mt-1" role="alert">
              @if (form.controls.email.errors?.['required']) {
                {{ 'auth.register.errors.email_required' | translate }}
              } @else {
                {{ 'auth.register.errors.email_invalid' | translate }}
              }
            </p>
          }
        </div>

        <div class="mb-4">
          <label for="displayName" class="block text-sm font-medium mb-1">{{ 'auth.register.display_name' | translate }}</label>
          <input id="displayName" type="text" formControlName="displayName" autocomplete="name"
                 [attr.aria-invalid]="isInvalid('displayName')"
                 class="w-full border rounded px-3 py-2" />
          @if (isInvalid('displayName')) {
            <p class="text-xs text-red-600 mt-1" role="alert">
              {{ 'auth.register.errors.display_name_required' | translate }}
            </p>
          }
        </div>

        <div class="mb-4">
          <label for="password" class="block text-sm font-medium mb-1">{{ 'auth.register.password' | translate }}</label>
          <input id="password" type="password" formControlName="password" autocomplete="new-password"
                 [attr.aria-invalid]="isInvalid('password')"
                 class="w-full border rounded px-3 py-2" />
          @if (isInvalid('password')) {
            <p class="text-xs text-red-600 mt-1" role="alert">
              @if (form.controls.password.errors?.['required']) {
                {{ 'auth.register.errors.password_required' | translate }}
              } @else if (form.controls.password.errors?.['minlength']) {
                {{ 'auth.register.errors.password_min' | translate }}
              } @else {
                {{ 'auth.register.errors.password_letters_digits' | translate }}
              }
            </p>
          } @else {
            <p class="text-xs text-gray-500 mt-1">{{ 'auth.register.password_hint' | translate }}</p>
          }
        </div>

        <button type="submit" [disabled]="form.invalid || facade.status() === 'loading'"
                class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:opacity-50">
          {{ 'auth.register.submit' | translate }}
        </button>
      </form>

      <p class="mt-4 text-sm text-center">
        {{ 'auth.register.have_account' | translate }}
        <a routerLink="/login" class="text-blue-600 hover:underline">{{ 'auth.register.login_link' | translate }}</a>
      </p>
    </div>
  `,
})
export class RegisterComponent {
  facade = inject(AuthFacade);
  private fb = inject(FormBuilder);

  form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    displayName: ['', [Validators.required, Validators.minLength(1), Validators.maxLength(64)]],
    password: ['', [Validators.required, Validators.minLength(12), lettersAndDigitsValidator]],
  });

  constructor() {
    // Reset stale 'loading' status from a prior screen so the submit
    // button isn't disabled when this page mounts. See LoginComponent
    // for the symmetric fix.
    this.facade.resetFormState();
  }

  /** Show a field's error only once the user has interacted with it. */
  isInvalid(name: 'email' | 'displayName' | 'password'): boolean {
    const c = this.form.controls[name];
    return c.invalid && (c.dirty || c.touched);
  }

  async onSubmit(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched(); // reveal what's wrong if they force-submit
      return;
    }
    const { email, displayName, password } = this.form.getRawValue();
    await this.facade.register(email, displayName, password);
  }
}
