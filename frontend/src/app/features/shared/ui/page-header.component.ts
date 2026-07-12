/** One page-header pattern (M10.5 §7.4) — title + optional subtitle + an
 * actions slot — replacing the five divergent header patterns. */
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

@Component({
  selector: 'app-page-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="mb-lg flex flex-wrap items-start justify-between gap-md">
      <div>
        <h1 class="text-2xl font-bold text-primary-900">{{ heading }}</h1>
        @if (subtitle) {
          <p class="mt-1 text-sm text-slate-600">{{ subtitle }}</p>
        }
      </div>
      <div class="flex items-center gap-sm">
        <ng-content select="[actions]" />
      </div>
    </header>
  `,
})
export class PageHeaderComponent {
  @Input({ required: true }) heading = '';
  @Input() subtitle = '';
}
