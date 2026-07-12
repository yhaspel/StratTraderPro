/** Shared empty-state (M10.5 §7.4) — a title, an optional description, and a
 * projected actions slot. Used for "no data yet" panels and the dashboard
 * getting-started empty state. */
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

@Component({
  selector: 'app-empty-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-xl text-center">
      <h3 class="text-base font-semibold text-slate-700">{{ heading }}</h3>
      @if (description) {
        <p class="mx-auto mt-1 max-w-md text-sm text-slate-500">{{ description }}</p>
      }
      <div class="mt-md flex justify-center gap-sm">
        <ng-content />
      </div>
    </div>
  `,
})
export class EmptyStateComponent {
  @Input({ required: true }) heading = '';
  @Input() description = '';
}
