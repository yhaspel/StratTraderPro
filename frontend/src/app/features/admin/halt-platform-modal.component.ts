/** HALT PLATFORM modal (M10) — engages the platform-wide kill switch.
 *
 * Typed-confirm gate: the operator must type "HALT PLATFORM" exactly, and enter
 * a current MFA code (reused `app-totp-input`), before the engage button is
 * enabled. The server re-validates both (400 CONFIRM_PHRASE_MISMATCH / 403
 * MFA_REQUIRED). Modal shell is the shared `app-modal` in destructive mode
 * (down-red title + danger primary), focus-trapped, OnPush, signals.
 */
import {
  ChangeDetectionStrategy, Component, EventEmitter, Output, inject, signal, computed,
} from '@angular/core';
import { NgClass } from '@angular/common';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';
import { ModalComponent } from '../shared/ui/modal.component';
import { ButtonComponent } from '../shared/ui/button.component';

const CONFIRM_PHRASE = 'HALT PLATFORM';

@Component({
  selector: 'app-halt-platform-modal',
  standalone: true,
  imports: [NgClass, TranslateModule, TotpInputComponent, ModalComponent, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-modal [open]="true" [heading]="modalHeading()" [destructive]="true" (closed)="closed.emit()">
        <p class="mb-4 text-sm text-neutral-600">{{ 'admin.halt.warning' | translate }}</p>

        <div class="mb-4">
          <label for="halt-reason-input" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">
            {{ 'admin.halt.reason_label' | translate }}
          </label>
          <input id="halt-reason-input" type="text" [value]="reason()"
                 (input)="reason.set($any($event.target).value)" autocomplete="off"
                 class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
        </div>

        <label for="halt-confirm-input" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">
          {{ 'admin.halt.confirm_label' | translate }}
        </label>
        <input id="halt-confirm-input" type="text" [value]="confirmText()"
               (input)="onConfirmInput($event)" autocomplete="off" spellcheck="false"
               class="mb-4 w-full rounded-none border-2 bg-surface px-3 py-2 font-mono text-sm text-ink"
               [ngClass]="phraseOk() ? 'border-up' : (confirmText().length > 0 ? 'border-down' : 'border-divider')"
               [attr.aria-invalid]="confirmText().length > 0 && !phraseOk()" />

        <span class="mb-2 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">
          {{ 'admin.halt.mfa_label' | translate }}
        </span>
        <app-totp-input [ariaLabel]="'MFA code'" (codeChange)="mfaCode.set($event)" [disabled]="submitting()" />

        @if (error(); as err) {
          <p class="mt-3 text-sm text-down">
            @if (knownError(err.code)) {
              {{ ('admin.halt.error.' + err.code) | translate }}
            } @else {
              {{ err.message }}
            }
          </p>
        }

        <div class="mt-6 flex justify-end gap-3">
          <app-button variant="ghost" (clicked)="closed.emit()">
            {{ 'common.cancel' | translate }}
          </app-button>
          <app-button variant="danger" [disabled]="!canEngage()" [loading]="submitting()" (clicked)="engage()">
            {{ (submitting() ? 'admin.halt.engaging' : 'admin.halt.engage') | translate }}
          </app-button>
        </div>
    </app-modal>
  `,
})
export class HaltPlatformModalComponent {
  @Output() closed = new EventEmitter<void>();
  @Output() halted = new EventEmitter<void>();

  private admin = inject(AdminFacade);
  private translate = inject(TranslateService);

  modalHeading(): string {
    return this.translate.instant('admin.halt.title');
  }

  confirmText = signal('');
  mfaCode = signal('');
  reason = signal('');
  submitting = signal(false);
  error = signal<ApiError | null>(null);

  readonly phraseOk = computed(() => this.confirmText() === CONFIRM_PHRASE);
  readonly canEngage = computed(
    () => this.phraseOk() && this.mfaCode().length === 6 && !this.submitting(),
  );

  onConfirmInput(ev: Event): void {
    this.confirmText.set((ev.target as HTMLInputElement).value);
  }

  async engage(): Promise<void> {
    if (!this.canEngage()) { return; }
    this.error.set(null);
    this.submitting.set(true);
    try {
      const res = await this.admin.killswitch({
        engage: true,
        reason: this.reason(),
        mfa_code: this.mfaCode(),
        confirm: this.confirmText(),
      });
      if (res.ok) {
        this.halted.emit();
      } else {
        this.error.set(res.error);
      }
    } finally {
      this.submitting.set(false);
    }
  }

  knownError(code: string): boolean {
    return code === 'CONFIRM_PHRASE_MISMATCH' || code === 'MFA_REQUIRED';
  }
}
