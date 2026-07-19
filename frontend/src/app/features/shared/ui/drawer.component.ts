/** Right-side detail drawer ("Industry" system) — extracted from the
 * hand-rolled orders drawer. 440px fixed panel on `--color-bg` with a left
 * hairline and `--shadow-lg`, over a scrim. Focus management mirrors
 * app-modal: saves the opener, moves focus in, traps Tab, closes on Escape
 * or scrim click, restores focus on close.
 */
import {
  ChangeDetectionStrategy, Component, ElementRef, EventEmitter, Input, OnDestroy, Output, ViewChild,
} from '@angular/core';

let drawerSeq = 0;

@Component({
  selector: 'app-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open) {
      <div
        class="fixed inset-0 z-50 bg-neutral-900/40"
        (click)="close()"></div>
      <aside
        #panel
        role="dialog"
        aria-modal="true"
        [attr.aria-labelledby]="titleId"
        tabindex="-1"
        (keydown)="onKeydown($event)"
        class="fixed inset-y-0 right-0 z-[51] flex w-[440px] max-w-full flex-col gap-s4 overflow-y-auto border-l border-divider bg-bg p-s6 shadow-lg focus:outline-none">
        <div class="flex items-center justify-between">
          <h2
            [id]="titleId"
            class="font-heading font-semibold text-[13px] uppercase tracking-[0.08em] text-neutral-700">{{ heading }}</h2>
          <button
            type="button"
            class="p-1 text-neutral-600 hover:text-neutral-800"
            [attr.aria-label]="closeLabel"
            (click)="close()">✕</button>
        </div>
        <ng-content />
      </aside>
    }
  `,
})
export class DrawerComponent implements OnDestroy {
  @Input() heading = '';
  @Input() closeLabel = 'Close';
  @Input() titleId = `drawer-title-${++drawerSeq}`;

  @Input()
  set open(value: boolean) {
    if (value === this._open) { return; }
    this._open = value;
    if (value) {
      this.previouslyFocused =
        typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null;
      queueMicrotask(() => this.focusPanel());
    } else {
      this.restoreFocus();
    }
  }
  get open(): boolean { return this._open; }
  private _open = false;

  @Output() closed = new EventEmitter<void>();
  @ViewChild('panel') panelRef?: ElementRef<HTMLElement>;
  private previouslyFocused: HTMLElement | null = null;

  ngOnDestroy(): void {
    if (this._open) { this.restoreFocus(); }
  }

  close(): void {
    this.closed.emit();
  }

  onKeydown(ev: KeyboardEvent): void {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      this.close();
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
    const root = this.panelRef?.nativeElement;
    if (!root) { return []; }
    return Array.from(
      root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), ' +
          'select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
  }

  private focusPanel(): void {
    const focusables = this.focusable();
    (focusables[0] ?? this.panelRef?.nativeElement)?.focus();
  }

  private restoreFocus(): void {
    this.previouslyFocused?.focus?.();
    this.previouslyFocused = null;
  }
}
