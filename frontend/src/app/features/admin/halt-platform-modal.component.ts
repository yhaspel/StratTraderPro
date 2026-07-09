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
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';

const CONFIRM_PHRASE = 'HALT PLATFORM';

@Component({
  selector: 'app-halt-platform-modal',
  standalone: true,
  imports: [TranslateModule, TotpInputComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="fixed inset-0 bg-black/50 z-40" (click)="onBackdropClick($event)">
      <div class="bg-white rounded-lg shadow-xl max-w-md mx-auto mt-16 p-6"
           (click)="$event.stopPropagation()" role="dialog" aria-modal="true">
        <div class="flex items-start justify-between mb-4">
          <h2 class="text-xl font-bold text-red-700">{{ 'admin.halt.title' | translate }}</h2>
          <button type="button" (click)="closed.emit()" [attr.aria-label]="'common.close' | translate"
                  class="text-gray-400 hover:text-gray-600 text-2xl leading-none">×</button>
        </div>

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

        <label class="block text-xs font-semibold text-gray-700 uppercase mb-2">
          {{ 'admin.halt.mfa_label' | translate }}
        </label>
        <app-totp-input (codeChange)="mfaCode.set($event)" [disabled]="submitting()" />

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
      </div>
    </div>
  `,
})
export class HaltPlatformModalComponent {
  @Output() closed = new EventEmitter<void>();
  @Output() halted = new EventEmitter<void>();

  private admin = inject(AdminFacade);

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

  onBackdropClick(ev: Event): void {
    if (ev.target === ev.currentTarget) { this.closed.emit(); }
  }
}
