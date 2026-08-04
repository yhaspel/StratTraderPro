/** Shared card surface (M10.5 §7.4, restyled for the "Industry" system).
 * Blueprint panel: transparent, hairline `--color-divider` border, square
 * corners, four "+" corner registration marks. */
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { BlueprintDirective } from './blueprint.directive';

@Component({
  selector: 'app-card',
  standalone: true,
  imports: [BlueprintDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section stpBlueprint class="block bg-transparent p-s4">
      <ng-content />
    </section>
  `,
})
export class CardComponent {}
