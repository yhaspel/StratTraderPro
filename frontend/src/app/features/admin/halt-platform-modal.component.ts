/** HALT PLATFORM modal (M10) — engages the platform-wide kill switch.
 *
 * Typed-confirm gate: the operator must type "HALT PLATFORM" exactly, and enter
 * a current MFA code (reused `app-totp-input`), before the engage button is
 * enabled. The server re-validates both (400 CONFIRM_PHRASE_MISMATCH / 403
 * MFA_REQUIRED). Modal shell mirrors webhook-config-modal (overlay, role=dialog,
 * backdrop close, OnPush, signals).
 */
import {
  ChangeDetectionStrategy, Component, EventEmitter, Output, inject, signal, computed,
} from '@angular/core';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';
import { ModalComponent } from '../shared/ui/modal.component';

const CONFIRM_PHRASE = 'HALT PLATFORM';

@Component({
  selector: 'app-halt-platform-modal',
  standalone: true,
  imports: [TranslateModule, TotpInputComponent, ModalComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-modal [open]="true" [heading]="modalHeading()" (closed)="closed.emit()">
        <p class="text-sm text-red-700 font-semibold mb-2">⚠ {{ 'admin.halt.title' | translate }}</p>
        <p class="text-sm text-gray-600 mb-4">{{ 'admin.halt.warning' | translate }}</p>

        <label for="halt-confirm-input" class="block text-xs font-semibold text-gray-700 uppercase mb-1">
          {{ 'admin.halt.confirm_label' | translate }}
        </label>
        <input id="halt-confirm-input" type="text" [value]="confirmText()"
               (input)="onConfirmInput($event)" autocomplete="off" spellcheck="false"
               class="w-full font-mono text-sm border-2 rounded px-3 py-2 mb-4"
               [class.border-red-400]="confirmText().length > 0 && !phraseOk()"
               [class.border-green-400]="phraseOk()"
               [attr.aria-invalid]="confirmText().length > 0 && !phraseOk()" />

        <span class="block text-xs font-semibold text-gray-700 uppercase mb-2">
          {{ 'admin.halt.mfa_label' | translate }}
        </span>
        <app-totp-input [ariaLabel]="'MFA code'" (codeChange)="mfaCode.set($event)" [disabled]="submitting()" />

        <div class="mt-4">
          <label for="halt-reason-input" class="block text-xs font-semibold text-gray-700 uppercase mb-1">
            {{ 'admin.halt.reason_label' | translate }}
          </label>
          <input id="halt-reason-input" type="text" [value]="reason()"
                 (input)="reason.set($any($event.target).value)" autocomplete="off"
                 class="w-full text-sm border rounded px-3 py-2" />
        </div>

        @if (error(); as err) {
          <p class="text-sm text-red-700 mt-3">
            @if (knownError(err.code)) {
              {{ ('admin.halt.error.' + err.code) | translate }}
            } @else {
              {{ err.message }}
            }
          </p>
        }

        <div class="flex gap-3 justify-end mt-6">
          <button type="button" (click)="closed.emit()"
                  class="px-4 py-2 rounded border text-sm hover:bg-gray-50">
            {{ 'common.cancel' | translate }}
          </button>
          <button type="button" (click)="engage()" [disabled]="!canEngage()"
                  class="bg-red-600 text-white px-4 py-2 rounded text-sm hover:bg-red-700 disabled:opacity-40">
            {{ (submitting() ? 'admin.halt.engaging' : 'admin.halt.engage') | translate }}
          </button>
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
