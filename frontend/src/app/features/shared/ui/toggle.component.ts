/** Square toggle ("Industry" system) — extracted from strategies-list.
 * 40×20 track: `--up` fill + border when on (enabled = money-adjacent state),
 * `--color-surface` + hairline when off; square 15×14 knob that slides.
 * Renders a native button with `role="switch"`; label via `ariaLabel`.
 */
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
  selector: 'app-toggle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      type="button"
      role="switch"
      [attr.aria-checked]="checked"
      [attr.aria-label]="ariaLabel || null"
      [disabled]="disabled"
      (click)="toggled.emit(!checked)"
      class="relative h-5 w-10 rounded-none border p-0 transition-colors disabled:opacity-45 disabled:cursor-not-allowed"
      [class.bg-up]="checked"
      [class.border-up]="checked"
      [class.bg-surface]="!checked"
      [class.border-divider]="!checked">
      <span
        aria-hidden="true"
        class="absolute top-[2px] h-3.5 w-[15px] transition-[left] duration-150 ease-in-out"
        [style.left.px]="checked ? 21 : 2"
        [class.bg-bg]="checked"
        [class.bg-neutral-400]="!checked"></span>
    </button>
  `,
})
export class ToggleComponent {
  @Input() checked = false;
  @Input() disabled = false;
  @Input() ariaLabel = '';
  @Output() toggled = new EventEmitter<boolean>();
}
