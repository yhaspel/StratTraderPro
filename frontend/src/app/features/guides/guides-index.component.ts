/** Guides index at /guides (M12 §7.1).
 *
 * Replaces the old flat /help list, which was reachable only from the user
 * dropdown and offered 13 unexplained titles in one column. Guides is now a
 * primary nav tab, grouped into sections with a one-line summary per article
 * and a filter box, so a user can find the instruction they need without
 * already knowing its name.
 *
 * Article bodies stay as static HTML in assets/guides/ (see
 * GuidesArticleComponent); this component only renders the catalog.
 */
import { ChangeDetectionStrategy, Component, computed, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

import { GUIDE_SECTIONS, GuideSection } from './guides.catalog';

@Component({
  selector: 'app-guides-index',
  standalone: true,
  imports: [RouterLink, TranslateModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mx-auto max-w-4xl">
      <h1 class="font-heading text-[32px] font-semibold leading-tight text-ink">{{ 'guides.index.title' | translate }}</h1>
      <p class="mt-1 text-sm text-neutral-700">{{ 'guides.index.subtitle' | translate }}</p>

      <label class="sr-only" for="guides-filter">{{ 'guides.index.filter' | translate }}</label>
      <input
        id="guides-filter"
        type="search"
        autocomplete="off"
        [placeholder]="'guides.index.filter' | translate"
        (input)="query.set($any($event.target).value)"
        class="mt-4 w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none" />

      @if (visible().length === 0) {
        <p class="mt-6 text-sm text-neutral-700" role="status">{{ 'guides.index.no_match' | translate }}</p>
      }

      @for (section of visible(); track section.key) {
        <section class="mt-7">
          <h2 class="mb-3 font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
            {{ section.title }}
          </h2>
          <ul class="grid gap-2 sm:grid-cols-2">
            @for (a of section.articles; track a.slug) {
              <li>
                <a
                  [routerLink]="['/guides', a.slug]"
                  class="block h-full rounded-none border border-divider px-3 py-2.5 no-underline transition-colors hover:bg-surface">
                  <span class="block font-heading text-sm font-semibold text-accent-700">{{ a.title }}</span>
                  <span class="mt-0.5 block text-[13px] leading-snug text-neutral-700">{{ a.summary }}</span>
                </a>
              </li>
            }
          </ul>
        </section>
      }
    </div>
  `,
})
export class GuidesIndexComponent {
  readonly query = signal('');

  /** Sections with non-matching articles removed, and empty sections dropped.
   *  Matches on title AND summary so "timezone" finds the profile guide even
   *  though the word is not in its title. */
  readonly visible = computed<GuideSection[]>(() => {
    const q = this.query().toLowerCase().trim();
    if (!q) { return GUIDE_SECTIONS; }
    return GUIDE_SECTIONS
      .map(s => ({
        ...s,
        articles: s.articles.filter(
          a => (s.title + ' ' + a.title + ' ' + a.summary).toLowerCase().includes(q),
        ),
      }))
      .filter(s => s.articles.length > 0);
  });
}
