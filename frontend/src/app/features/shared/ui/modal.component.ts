/** Shared modal (M10.5 §7.4) — in-house focus trap (no @angular/cdk per F-12).
 *
 * On open: saves `document.activeElement`, moves focus into the dialog, traps
 * Tab within it, closes on Escape or backdrop click, and restores focus on
 * close. `role="dialog" aria-modal="true"` with a labelled title (AC-10.5-13).
 *
 * Set `[dismissable]="false"` for a BLOCKING modal (M11 §7.8): Escape and
 * backdrop clicks are ignored and the ✕ close affordance is hidden, so the
 * only way out is an in-content action. Tab-trapping still applies.
 */
import {
  ChangeDetectionStrategy, Component, ElementRef, EventEmitter, Input, OnDestroy, Output, ViewChild,
} from '@angular/core';

let modalSeq = 0;

@Component({
  selector: 'app-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open) {
      <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        (click)="onBackdrop($event)">
        <div
          #dialog
          role="dialog"
          aria-modal="true"
          [attr.aria-labelledby]="titleId"
          tabindex="-1"
          (keydown)="onKeydown($event)"
          class="w-full max-w-lg rounded-lg bg-white p-lg shadow-md focus:outline-none">
          <div class="mb-md flex items-start justify-between gap-md">
            <h2 [id]="titleId" class="text-lg font-semibold text-primary-900">{{ heading }}</h2>
            @if (dismissable) {
              <button
                type="button"
                class="rounded p-1 text-slate-400 hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
                [attr.aria-label]="closeLabel"
                (click)="close()">✕</button>
            }
          </div>
          <ng-content />
        </div>
      </div>
    }
  `,
})
export class ModalComponent implements OnDestroy {
  @Input() heading = '';
  @Input() closeLabel = 'Close';
  @Input() titleId = `modal-title-${++modalSeq}`;
  /** When false the modal is blocking: Escape/backdrop are ignored and the ✕
   * affordance is hidden (M11 §7.8). Defaults true (existing behaviour). */
  @Input() dismissable = true;

  @Input()
  set open(value: boolean) {
    if (value === this._open) { return; }
    this._open = value;
    if (value) {
      this.previouslyFocused =
        typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null;
      queueMicrotask(() => this.focusDialog());
    } else {
      this.restoreFocus();
    }
  }
  get open(): boolean { return this._open; }
  private _open = false;

  @Output() closed = new EventEmitter<void>();
  @ViewChild('dialog') dialogRef?: ElementRef<HTMLElement>;
  private previouslyFocused: HTMLElement | null = null;

  ngOnDestroy(): void {
    // Parents that render the modal via `@if` destroy it on close rather than
    // toggling [open] to false, so restore focus here too (AC-10.5-13).
    if (this._open) { this.restoreFocus(); }
  }

  close(): void {
    this.closed.emit();
  }

  onBackdrop(ev: MouseEvent): void {
    if (this.dismissable && ev.target === ev.currentTarget) { this.close(); }
  }

  onKeydown(ev: KeyboardEvent): void {
    if (ev.key === 'Escape') {
      if (this.dismissable) { ev.preventDefault(); this.close(); }
      return;
    }
    if (ev.key !== 'Tab') { return; }
    const focusables = this.focusable();
    if (focusables.length === 0) { ev.preventDefault(); return; }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;
    if (ev.shiftKey && active === first) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && active === last) {
      ev.preventDefault();
      first.focus();
    }
  }

  private focusable(): HTMLElement[] {
    const root = this.dialogRef?.nativeElement;
    if (!root) { return []; }
    return Array.from(
      root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), ' +
          'select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
  }

  private focusDialog(): void {
    const focusables = this.focusable();
    (focusables[0] ?? this.dialogRef?.nativeElement)?.focus();
  }

  private restoreFocus(): void {
    this.previouslyFocused?.focus?.();
    this.previouslyFocused = null;
  }
}
