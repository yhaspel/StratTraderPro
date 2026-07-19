import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { BlueprintDirective } from '../../shared/ui/blueprint.directive';

@Component({
  selector: 'app-password-reset',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, RouterLink, TranslateModule,
    ButtonComponent, CardComponent, BlueprintDirective,
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
          <h1 class="m-0 font-heading text-2xl font-semibold text-ink">{{ 'auth.reset.title' | translate }}</h1>
        </div>

        <app-card>
          @if (sent()) {
            <div class="bg-accent-100 px-4 py-3 text-sm text-accent-800">
              {{ 'auth.reset.sent' | translate }}
            </div>
          } @else {
            <p class="mb-4 mt-0 text-sm text-neutral-700">{{ 'auth.reset.description' | translate }}</p>
            @if (error()) {
              <div role="alert" class="mb-4 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep">
                {{ 'auth.reset.error' | translate }}
              </div>
            }
            <form [formGroup]="form" (ngSubmit)="onSubmit()">
              <div class="mb-4">
                <label for="email" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.reset.email' | translate }}</label>
                <input id="email" type="email" formControlName="email" autocomplete="email"
                       class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
              </div>
              <app-button type="submit" variant="primary" [frame]="true"
                          class="block [&>button]:w-full"
                          [disabled]="form.invalid || loading()"
                          [loading]="loading()">
                {{ 'auth.reset.submit' | translate }}
              </app-button>
            </form>
          }
        </app-card>

        <p class="m-0 text-center text-[13px]">
          <a routerLink="/login" class="text-accent-700 hover:underline">{{ 'auth.reset.back_to_login' | translate }}</a>
        </p>
      </div>
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
