/**
 * 6-cell TOTP input — pasted codes auto-distribute, single keystrokes
 * auto-advance. Backspace empties the current cell, then steps left.
 *
 * Used by:
 *  - /login/mfa (MFA challenge)
 *  - /settings/security/mfa/setup (enrollment confirm)
 *  - /settings/security (regenerate, disable)
 */
import {
  Component, ElementRef, EventEmitter, Input, Output,
  QueryList, ViewChildren, AfterViewInit, signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-totp-input',
  standalone: true,
  imports: [CommonModule],
  template: `
    <fieldset class="flex gap-2 justify-center" role="group" [attr.aria-label]="ariaLabel">
      @for (i of cells; track i) {
        <input
          #cell
          type="text"
          inputmode="numeric"
          autocomplete="one-time-code"
          maxlength="1"
          [attr.aria-label]="ariaLabel + ' digit ' + (i + 1)"
          [disabled]="disabled"
          [value]="digits()[i] || ''"
          (input)="onInput($event, i)"
          (keydown)="onKeyDown($event, i)"
          (paste)="onPaste($event)"
          class="h-[54px] w-11 rounded-none border border-divider bg-surface text-center font-mono text-[22px] text-ink caret-accent
                 focus:outline-none focus:border-2 focus:border-accent
                 disabled:opacity-45 disabled:cursor-not-allowed"
        />
      }
    </fieldset>
  `,
})
export class TotpInputComponent implements AfterViewInit {
  @Input() ariaLabel = 'Verification code';
  @Input() disabled = false;
  @Output() codeChange = new EventEmitter<string>();
  @Output() codeComplete = new EventEmitter<string>();

  cells = [0, 1, 2, 3, 4, 5];
  digits = signal<string[]>(['', '', '', '', '', '']);

  @ViewChildren('cell') inputs!: QueryList<ElementRef<HTMLInputElement>>;

  ngAfterViewInit(): void {
    queueMicrotask(() => this.inputs.first?.nativeElement.focus());
  }

  onInput(ev: Event, index: number): void {
    const target = ev.target as HTMLInputElement;
    const ch = (target.value || '').replace(/\D/g, '').slice(-1);
    const next = [...this.digits()];
    next[index] = ch;
    this.digits.set(next);
    target.value = ch;
    this.emit();
    if (ch && index < 5) {
      this.focusCell(index + 1);
    }
  }

  onKeyDown(ev: KeyboardEvent, index: number): void {
    if (ev.key === 'Backspace') {
      const next = [...this.digits()];
      if (!next[index] && index > 0) {
        next[index - 1] = '';
        this.digits.set(next);
        this.focusCell(index - 1);
        ev.preventDefault();
      } else if (next[index]) {
        next[index] = '';
        this.digits.set(next);
        this.emit();
        ev.preventDefault();
      }
    } else if (ev.key === 'ArrowLeft' && index > 0) {
      this.focusCell(index - 1);
      ev.preventDefault();
    } else if (ev.key === 'ArrowRight' && index < 5) {
      this.focusCell(index + 1);
      ev.preventDefault();
    }
  }

  onPaste(ev: ClipboardEvent): void {
    ev.preventDefault();
    const raw = (ev.clipboardData?.getData('text') || '').replace(/\D/g, '').slice(0, 6);
    if (!raw) return;
    const next = ['', '', '', '', '', ''];
    for (let i = 0; i < raw.length; i++) next[i] = raw[i];
    this.digits.set(next);
    // Sync DOM values explicitly because the bound [value] won't fire change.
    this.inputs.forEach((ref, i) => { ref.nativeElement.value = next[i] || ''; });
    this.focusCell(Math.min(raw.length, 5));
    this.emit();
  }

  /** Public API: clear all cells, useful after a failed verify. */
  clear(): void {
    this.digits.set(['', '', '', '', '', '']);
    this.inputs?.forEach(ref => { ref.nativeElement.value = ''; });
    this.focusCell(0);
    this.emit();
  }

  private focusCell(index: number): void {
    this.inputs.toArray()[index]?.nativeElement.focus();
  }

  private emit(): void {
    const code = this.digits().join('');
    this.codeChange.emit(code);
    if (code.length === 6) {
      this.codeComplete.emit(code);
    }
  }
}
