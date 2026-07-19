/** Inline help affordance (M10.5 §7.3/AC-10.5-6) — a small "?" that opens the
 * matching help article at /help/:slug next to a piece of jargon. */
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-help-link',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      [routerLink]="['/help', slug]"
      class="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-none border border-divider text-[10px] font-semibold text-neutral-700 hover:bg-accent-100 hover:text-accent-700"
      [attr.aria-label]="label">?</a>
  `,
})
export class HelpLinkComponent {
  @Input({ required: true }) slug = '';
  @Input() label = 'Help';
}
