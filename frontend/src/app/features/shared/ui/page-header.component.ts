/** One page-header pattern (M10.5 §7.4) — title + optional subtitle + an
 * actions slot — replacing the five divergent header patterns. */
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

@Component({
  selector: 'app-page-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="mb-s6 flex flex-wrap items-start justify-between gap-s3">
      <div>
        <h1 class="font-heading font-semibold text-[32px] leading-[1.12] tracking-tight text-ink">{{ heading }}</h1>
        @if (subtitle) {
          <p class="mt-0.5 text-sm text-neutral-600">{{ subtitle }}</p>
        }
      </div>
      <div class="flex items-center gap-s2">
        <ng-content select="[actions]" />
      </div>
    </header>
  `,
})
export class PageHeaderComponent {
  @Input({ required: true }) heading = '';
  @Input() subtitle = '';
}
