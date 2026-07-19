import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { BlueprintDirective } from '../../shared/ui/blueprint.directive';

@Component({
  selector: 'app-password-reset-confirm',
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
          <h1 class="m-0 font-heading text-2xl font-semibold text-ink">{{ 'auth.reset_confirm.title' | translate }}</h1>
        </div>

        @if (facade.error(); as err) {
          <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
            {{ err.message }}
          </div>
        }

        <app-card>
          <form [formGroup]="form" (ngSubmit)="onSubmit()">
            <div class="mb-4">
              <label for="password" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.reset_confirm.password' | translate }}</label>
              <input id="password" type="password" formControlName="password" autocomplete="new-password"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
              <p class="mt-1 text-[11px] text-neutral-600">{{ 'auth.register.password_hint' | translate }}</p>
            </div>

            <div class="mb-4">
              <label for="confirmPassword" class="mb-1 block text-xs font-medium text-neutral-700">{{ 'auth.reset_confirm.confirm_password' | translate }}</label>
              <input id="confirmPassword" type="password" formControlName="confirmPassword" autocomplete="new-password"
                     class="min-h-[36px] w-full rounded-none border border-divider bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none" />
            </div>

            <app-button type="submit" variant="primary" [frame]="true"
                        class="block [&>button]:w-full"
                        [disabled]="form.invalid || facade.status() === 'loading'"
                        [loading]="facade.status() === 'loading'">
              {{ 'auth.reset_confirm.submit' | translate }}
            </app-button>
          </form>
        </app-card>

        <p class="m-0 text-center text-[13px]">
          <a routerLink="/login" class="text-accent-700 hover:underline">{{ 'auth.reset_confirm.back_to_login' | translate }}</a>
        </p>
      </div>
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
