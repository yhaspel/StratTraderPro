import { Component, ElementRef, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AbstractControl, ReactiveFormsModule, FormBuilder, ValidationErrors, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { GoogleButtonComponent } from '../google-button/google-button.component';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { BlueprintDirective } from '../../shared/ui/blueprint.directive';

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
          <h1 class="m-0 font-heading text-2xl font-semibold text-ink">{{ 'auth.register.title' | translate }}</h1>
        </div>

        @if (facade.error(); as err) {
          <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
            {{ err.message }}
          </div>
        }

        <app-card>
          <app-google-button />

          <form [formGroup]="form" (ngSubmit)="onSubmit()">
            <div class="mb-4">
              <label for="email" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.register.email' | translate }}</label>
              <input id="email" type="email" formControlName="email" autocomplete="email"
                     [attr.aria-invalid]="isInvalid('email')"
                     [attr.aria-describedby]="isInvalid('email') ? 'email-error' : null"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
              @if (isInvalid('email')) {
                <p id="email-error" class="mt-1 text-xs text-down-deep" role="alert">
                  @if (form.controls.email.errors?.['required']) {
                    {{ 'auth.register.errors.email_required' | translate }}
                  } @else {
                    {{ 'auth.register.errors.email_invalid' | translate }}
                  }
                </p>
              }
            </div>

            <div class="mb-4">
              <label for="displayName" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.register.display_name' | translate }}</label>
              <input id="displayName" type="text" formControlName="displayName" autocomplete="name"
                     [attr.aria-invalid]="isInvalid('displayName')"
                     [attr.aria-describedby]="isInvalid('displayName') ? 'displayName-error' : null"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
              @if (isInvalid('displayName')) {
                <p id="displayName-error" class="mt-1 text-xs text-down-deep" role="alert">
                  {{ 'auth.register.errors.display_name_required' | translate }}
                </p>
              }
            </div>

            <div class="mb-4">
              <label for="password" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.register.password' | translate }}</label>
              <input id="password" type="password" formControlName="password" autocomplete="new-password"
                     [attr.aria-invalid]="isInvalid('password')"
                     [attr.aria-describedby]="isInvalid('password') ? 'password-error' : null"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
              @if (isInvalid('password')) {
                <p id="password-error" class="mt-1 text-xs text-down-deep" role="alert">
                  @if (form.controls.password.errors?.['required']) {
                    {{ 'auth.register.errors.password_required' | translate }}
                  } @else if (form.controls.password.errors?.['minlength']) {
                    {{ 'auth.register.errors.password_min' | translate }}
                  } @else {
                    {{ 'auth.register.errors.password_letters_digits' | translate }}
                  }
                </p>
              } @else {
                <p class="mt-1 text-[11px] text-neutral-700">{{ 'auth.register.password_hint' | translate }}</p>
              }
            </div>

            <app-button type="submit" variant="primary" [frame]="true"
                        class="block [&>button]:w-full"
                        [disabled]="facade.status() === 'loading'"
                        [loading]="facade.status() === 'loading'">
              {{ 'auth.register.submit' | translate }}
            </app-button>
          </form>
        </app-card>

        <p class="m-0 text-center text-[13px] text-neutral-700">
          {{ 'auth.register.have_account' | translate }}
          <a routerLink="/login" class="text-accent-700 hover:underline">{{ 'auth.register.login_link' | translate }}</a>
        </p>
      </div>
    </div>
  `,
})
export class RegisterComponent {
  facade = inject(AuthFacade);
  private fb = inject(FormBuilder);
  private host = inject(ElementRef) as ElementRef<HTMLElement>;

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
      // P2-DESIGN-6: button stays enabled; reveal errors + focus the first one.
      this.form.markAllAsTouched();
      this.focusFirstInvalid();
      return;
    }
    const { email, displayName, password } = this.form.getRawValue();
    await this.facade.register(email, displayName, password);
  }

  /** P2-DESIGN-6: move keyboard focus to the first invalid control. */
  private focusFirstInvalid(): void {
    (this.host.nativeElement.querySelector(
      'input.ng-invalid, select.ng-invalid, textarea.ng-invalid',
    ) as HTMLElement | null)?.focus();
  }
}
