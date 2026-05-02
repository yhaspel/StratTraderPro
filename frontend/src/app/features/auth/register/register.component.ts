import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { GoogleButtonComponent } from '../google-button/google-button.component';

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

      <app-google-button class="block mb-4" />

      <div class="my-4 flex items-center text-xs text-gray-500">
        <span class="flex-1 border-t border-gray-300"></span>
        <span class="px-3">{{ 'oauth.or' | translate }}</span>
        <span class="flex-1 border-t border-gray-300"></span>
      </div>

      <form [formGroup]="form" (ngSubmit)="onSubmit()">
        <div class="mb-4">
          <label for="email" class="block text-sm font-medium mb-1">{{ 'auth.register.email' | translate }}</label>
          <input id="email" type="email" formControlName="email" autocomplete="email"
                 class="w-full border rounded px-3 py-2" />
        </div>

        <div class="mb-4">
          <label for="displayName" class="block text-sm font-medium mb-1">{{ 'auth.register.display_name' | translate }}</label>
          <input id="displayName" type="text" formControlName="displayName" autocomplete="name"
                 class="w-full border rounded px-3 py-2" />
        </div>

        <div class="mb-4">
          <label for="password" class="block text-sm font-medium mb-1">{{ 'auth.register.password' | translate }}</label>
          <input id="password" type="password" formControlName="password" autocomplete="new-password"
                 class="w-full border rounded px-3 py-2" />
          <p class="text-xs text-gray-500 mt-1">{{ 'auth.register.password_hint' | translate }}</p>
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
    password: ['', [Validators.required, Validators.minLength(12)]],
  });

  async onSubmit(): Promise<void> {
    if (this.form.invalid) return;
    const { email, displayName, password } = this.form.getRawValue();
    await this.facade.register(email, displayName, password);
  }
}
