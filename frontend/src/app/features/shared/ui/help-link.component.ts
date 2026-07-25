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
    <!-- P3-13: the tap target is ≥24×24 (WCAG 2.5.8) while the visual "?" stays
         small — the padded anchor is the hit area, the inner span is the glyph. -->
    <a
      [routerLink]="['/help', slug]"
      class="group ml-1 inline-flex h-6 w-6 items-center justify-center rounded-none focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      [attr.aria-label]="label">
      <span class="inline-flex h-4 w-4 items-center justify-center rounded-none border border-divider text-[10px] font-semibold text-neutral-700 group-hover:bg-accent-100 group-hover:text-accent-700">?</span>
    </a>
  `,
})
export class HelpLinkComponent {
  @Input({ required: true }) slug = '';
  @Input() label = 'Help';
}
