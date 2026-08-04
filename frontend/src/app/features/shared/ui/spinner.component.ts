/** Shared spinner (M10.5 §7.4). role=status so screen readers announce loading. */
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

@Component({
  selector: 'app-spinner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span role="status" [attr.aria-label]="label" class="inline-flex items-center gap-s2 text-neutral-700">
      <span
        class="inline-block h-5 w-5 rounded-full border-2 border-current border-t-transparent animate-spin"
        aria-hidden="true"></span>
      @if (label) {
        <span class="text-sm">{{ label }}</span>
      }
    </span>
  `,
})
export class SpinnerComponent {
  @Input() label = '';
}
