import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

@Component({
  selector: 'app-password-reset-confirm',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslateModule],
  template: `
    <div class="mx-auto max-w-md p-6">
      <h1 class="text-2xl font-bold mb-6">{{ 'auth.reset_confirm.title' | translate }}</h1>

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ err.message }}
        </div>
      }

      <form [formGroup]="form" (ngSubmit)="onSubmit()">
        <div class="mb-4">
          <label for="password" class="block text-sm font-medium mb-1">{{ 'auth.reset_confirm.password' | translate }}</label>
          <input id="password" type="password" formControlName="password" autocomplete="new-password"
                 class="w-full border rounded px-3 py-2" />
          <p class="text-xs text-gray-500 mt-1">{{ 'auth.register.password_hint' | translate }}</p>
        </div>

        <div class="mb-4">
          <label for="confirmPassword" class="block text-sm font-medium mb-1">{{ 'auth.reset_confirm.confirm_password' | translate }}</label>
          <input id="confirmPassword" type="password" formControlName="confirmPassword" autocomplete="new-password"
                 class="w-full border rounded px-3 py-2" />
        </div>

        <button type="submit" [disabled]="form.invalid || facade.status() === 'loading'"
                class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:opacity-50">
          {{ 'auth.reset_confirm.submit' | translate }}
        </button>
      </form>

      <p class="mt-4 text-sm text-center">
        <a routerLink="/login" class="text-blue-600 hover:underline">{{ 'auth.reset_confirm.back_to_login' | translate }}</a>
      </p>
    </div>
  `,
})
export class PasswordResetConfirmComponent {
  facade = inject(AuthFacade);
  private fb = inject(FormBuilder);
  private route = inject(ActivatedRoute);

  form = this.fb.nonNullable.group({
    password: ['', [Validators.required, Validators.minLength(12)]],
    confirmPassword: ['', Validators.required],
  });

  async onSubmit(): Promise<void> {
    if (this.form.invalid) return;
    const { password, confirmPassword } = this.form.getRawValue();
    if (password !== confirmPassword) return;
    const token = this.route.snapshot.queryParamMap.get('token') || '';
    if (!token) return;
    await this.facade.passwordResetConfirm(token, password);
  }
}
