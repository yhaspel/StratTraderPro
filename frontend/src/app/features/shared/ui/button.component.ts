/** Shared button (M10.5 §7.4). One canonical disabled/loading treatment so the
 * `disabled:opacity-40` vs `-50` drift across screens stops. Token-driven. */
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

export type ButtonVariant = 'primary' | 'secondary' | 'danger';

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
      (click)="clicked.emit($event)">
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
  @Output() clicked = new EventEmitter<MouseEvent>();

  private readonly base =
    'inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium ' +
    'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 ' +
    'focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';

  private readonly byVariant: Record<ButtonVariant, string> = {
    primary: 'bg-primary-600 text-white hover:bg-primary-700',
    secondary: 'border border-primary-600 text-primary-700 bg-white hover:bg-primary-50',
    danger: 'bg-danger-500 text-white hover:opacity-90',
  };

  classes(): string {
    return `${this.base} ${this.byVariant[this.variant]}`;
  }
}
