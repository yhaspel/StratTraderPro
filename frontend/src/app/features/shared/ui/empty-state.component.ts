/** Shared empty-state (M10.5 §7.4) — a title, an optional description, and a
 * projected actions slot. Used for "no data yet" panels and the dashboard
 * getting-started empty state. */
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

@Component({
  selector: 'app-empty-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="rounded-none border border-dashed border-neutral-400 bg-transparent p-s8 text-center">
      <h3 class="font-heading font-semibold text-base text-neutral-700">{{ heading }}</h3>
      @if (description) {
        <p class="mx-auto mt-1 max-w-md text-sm text-neutral-600">{{ description }}</p>
      }
      <div class="mt-s3 flex justify-center gap-s2">
        <ng-content />
      </div>
    </div>
  `,
})
export class EmptyStateComponent {
  @Input({ required: true }) heading = '';
  @Input() description = '';
}
