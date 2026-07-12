import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

@Component({
  selector: 'app-password-reset',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslateModule],
  template: `
    <div class="mx-auto max-w-md p-6">
      <h1 class="text-2xl font-bold mb-6">{{ 'auth.reset.title' | translate }}</h1>

      @if (sent()) {
        <div class="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded mb-4">
          {{ 'auth.reset.sent' | translate }}
        </div>
      } @else {
        <p class="mb-4 text-gray-600">{{ 'auth.reset.description' | translate }}</p>
        @if (error()) {
          <div role="alert" class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
            {{ 'auth.reset.error' | translate }}
          </div>
        }
        <form [formGroup]="form" (ngSubmit)="onSubmit()">
          <div class="mb-4">
            <label for="email" class="block text-sm font-medium mb-1">{{ 'auth.reset.email' | translate }}</label>
            <input id="email" type="email" formControlName="email" autocomplete="email"
                   class="w-full border rounded px-3 py-2" />
          </div>
          <button type="submit" [disabled]="form.invalid || loading()"
                  class="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:opacity-50">
            {{ 'auth.reset.submit' | translate }}
          </button>
        </form>
      }

      <p class="mt-4 text-sm text-center">
        <a routerLink="/login" class="text-blue-600 hover:underline">{{ 'auth.reset.back_to_login' | translate }}</a>
      </p>
    </div>
  `,
})
export class PasswordResetComponent {
  private facade = inject(AuthFacade);
  private fb = inject(FormBuilder);

  form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
  });

  sent = signal(false);
  loading = signal(false);
  error = signal(false);

  async onSubmit(): Promise<void> {
    if (this.form.invalid) return;
    this.loading.set(true);
    this.error.set(false);
    const ok = await this.facade.passwordReset(this.form.getRawValue().email);
    this.loading.set(false);
    if (ok) {
      this.sent.set(true);
    } else {
      this.error.set(true);
    }
  }
}
