/** Shared card surface (M10.5 §7.4). Token-driven padding + shadow. */
import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  selector: 'app-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="rounded-lg border border-slate-200 bg-white p-lg shadow-sm">
      <ng-content />
    </section>
  `,
})
export class CardComponent {}
