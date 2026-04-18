import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, TranslateModule],
  template: `
    <div class="mx-auto max-w-md p-6">
      <h1 class="text-2xl font-bold mb-6">{{ 'auth.login.title' | translate }}</h1>

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ 'auth.login.error.' + err.code | translate : { default: err.message } }}
        </div>
      }

      <form [formGroup]="form" (ngSubmit)="onSubmit()">
        <div class="mb-4">
          <label for="email" class="block text-sm font-medium mb-1">{{ 'auth.login.email' | translate }}</label>
          <input id="email" type="email" formControlName="email" autocomplete="email"
                 class="w-full border rounded px-3 py-2" />
        </div>

        <div class="mb-4">
          <label for="password" class="block text-sm font-medium mb-1">{{ 'auth.login.password' | translate }}</label>
          <input id="password" type="password" formControlName="password" autocomplete="current-password"
                 class="w-full border rounded px-3 py-2" />
        </div>

        <button type="submit" [disabled]="form.invalid || facade.status() === 'loading'"
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

  async onSubmit(): Promise<void> {
    if (this.form.invalid) return;
    const { email, password } = this.form.getRawValue();
    await this.facade.login(email, password);
  }
}
