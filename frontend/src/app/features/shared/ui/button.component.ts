/** Shared button (M10.5 §7.4, restyled for the "Industry" system). One
 * canonical disabled/loading treatment. Token-driven: square corners, Barlow
 * Condensed 600 14px, disabled 45% opacity, themed hover/pressed states.
 *
 * Variants — primary (the one solid accent object), secondary (hairline),
 * ghost (accent text), danger (solid `--down`), success (solid `--up`; used
 * ONLY for Release actions). Set `frame` on hero/submit primaries to add the
 * blueprint corner registration marks.
 */
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';

@Component({
  selector: 'app-button',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      [type]="type"
      [disabled]="disabled || loading"
      [attr.aria-busy]="loading ? 'true' : null"
      [class]="classes()"
      [class.blueprint]="frame"
      (click)="clicked.emit($event)">
      @if (frame) {
        <i class="corner tl" aria-hidden="true"></i>
        <i class="corner tr" aria-hidden="true"></i>
        <i class="corner bl" aria-hidden="true"></i>
        <i class="corner br" aria-hidden="true"></i>
      }
      @if (loading) {
        <span
          class="inline-block h-4 w-4 rounded-full border-2 border-current border-t-transparent animate-spin"
          [class.mr-2]="true"
          aria-hidden="true"></span>
      }
      <ng-content />
    </button>
  `,
})
export class ButtonComponent {
  @Input() variant: ButtonVariant = 'primary';
  @Input() type: 'button' | 'submit' = 'button';
  @Input() disabled = false;
  @Input() loading = false;
  /** Blueprint corner registration marks — hero/submit primary uses only. */
  @Input() frame = false;
  @Output() clicked = new EventEmitter<MouseEvent>();

  private readonly base =
    'relative inline-flex items-center justify-center gap-1.5 rounded-none border ' +
    'font-heading font-semibold text-sm leading-tight px-3 py-1.5 ' +
    'transition-colors disabled:opacity-45 disabled:cursor-not-allowed';

  private readonly byVariant: Record<ButtonVariant, string> = {
    primary: 'bg-accent border-accent text-bg hover:bg-accent-600 active:bg-accent-700',
    secondary: 'bg-transparent border-divider text-ink hover:bg-neutral-200 active:bg-neutral-300',
    ghost:
      'bg-transparent border-transparent text-accent-700 px-1 hover:bg-accent-100 active:bg-accent-200',
    danger: 'bg-down border-down text-bg hover:opacity-90 active:bg-down-deep',
    success: 'bg-up border-up text-bg hover:opacity-90 active:bg-up-deep',
  };

  classes(): string {
    return `${this.base} ${this.byVariant[this.variant]}`;
  }
}
