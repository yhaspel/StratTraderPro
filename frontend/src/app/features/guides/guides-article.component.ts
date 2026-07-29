/** Guide viewer at /guides/:slug (M12 §7.1, was /help/:slug).
 *
 * Loads the first-party static HTML from assets/guides/<slug>.html and binds it
 * to [innerHTML] so Angular's default sanitizer runs (P2-12) — the styled tags
 * (h1/h2/p/ul/ol/a/code/pre/img/table) all survive, but any injected
 * <script>/onerror is stripped, so a malicious guide file (public repo, PRs)
 * can't run in an authed session.
 *
 * The slug is validated against the GUIDE_SLUGS catalog, not just a character
 * class: an unknown-but-well-formed slug now 404s without issuing a request,
 * and the catalog also supplies prev/next.
 */
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

import { GUIDE_ARTICLES, GUIDE_SLUGS, GuideArticle, findGuide } from './guides.catalog';

@Component({
  selector: 'app-guides-article',
  standalone: true,
  imports: [RouterLink, TranslateModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="mx-auto max-w-3xl">
      <a routerLink="/guides" class="inline-block rounded-none px-1 text-[13px] text-accent-700 transition-colors hover:bg-accent-100">
        ← {{ 'guides.back' | translate }}
      </a>

      @if (loading()) {
        <p class="mt-4 text-neutral-700">{{ 'common.loading' | translate }}</p>
      } @else if (notFound()) {
        <h1 class="mt-2 font-heading text-[32px] font-semibold leading-tight text-ink">{{ 'help.not_found.title' | translate }}</h1>
        <p class="mt-2 text-neutral-700">{{ 'help.not_found.body' | translate }}</p>
        <a routerLink="/guides" class="mt-4 inline-flex text-accent-700 underline">
          {{ 'guides.index.title' | translate }}
        </a>
      } @else {
        <div class="help-content mt-2 leading-relaxed text-ink" [innerHTML]="content()"></div>

        <!-- Sequential navigation: the guides are written to be read in order
             within a section, and a dead end at the bottom of an article is the
             main reason people bounce back to the index and give up. -->
        <nav class="mt-10 flex flex-wrap justify-between gap-4 border-t border-divider pt-4 text-[13px]"
             [attr.aria-label]="'guides.nav' | translate">
          <span>
            @if (prev(); as p) {
              <a [routerLink]="['/guides', p.slug]" class="text-accent-700 underline">← {{ p.title }}</a>
            }
          </span>
          <span class="text-right">
            @if (next(); as n) {
              <a [routerLink]="['/guides', n.slug]" class="text-accent-700 underline">{{ n.title }} →</a>
            }
          </span>
        </nav>
      }
    </article>
  `,
  styles: [`
    .help-content ::ng-deep h1 { font-family: var(--font-heading); font-size: 1.75rem; font-weight: 600; margin-bottom: 0.75rem; }
    .help-content ::ng-deep h2 { font-family: var(--font-heading); font-size: 1.25rem; font-weight: 600; margin: 1.5rem 0 0.5rem; }
    .help-content ::ng-deep h3 { font-family: var(--font-heading); font-size: 1.05rem; font-weight: 600; margin: 1.25rem 0 0.4rem; }
    .help-content ::ng-deep p { margin-bottom: 0.75rem; }
    .help-content ::ng-deep ul { list-style: disc; padding-inline-start: 1.5rem; margin-bottom: 0.75rem; }
    .help-content ::ng-deep ol { list-style: decimal; padding-inline-start: 1.5rem; margin-bottom: 0.75rem; }
    .help-content ::ng-deep li { margin-bottom: 0.35rem; }
    .help-content ::ng-deep a { color: var(--color-accent-700); text-decoration: underline; }
    .help-content ::ng-deep code { font-family: var(--font-mono), monospace; background: var(--color-surface); padding: 0 0.25rem; border-radius: 0; }
    .help-content ::ng-deep pre { background: var(--color-surface); border: 1px solid var(--color-divider); padding: 0.75rem; overflow-x: auto; font-size: 0.8rem; margin-bottom: 0.75rem; }
    .help-content ::ng-deep pre code { background: transparent; padding: 0; }
    .help-content ::ng-deep table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; font-size: 0.85rem; }
    .help-content ::ng-deep th, .help-content ::ng-deep td { border: 1px solid var(--color-divider); padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }
    .help-content ::ng-deep th { background: var(--color-surface); font-weight: 600; }
    /* Step screenshots — framed like every other panel in the design system. */
    .help-content ::ng-deep figure { margin: 0 0 1rem; }
    .help-content ::ng-deep img { display: block; width: 100%; height: auto; border: 1px solid var(--color-divider); }
    .help-content ::ng-deep figcaption { margin-top: 0.35rem; font-size: 0.75rem; color: var(--color-neutral-700); }
    .help-content ::ng-deep .warn { border: 1px solid var(--color-warn); background: var(--color-warn-tint); padding: 0.75rem; margin-bottom: 1rem; }
  `],
})
export class GuidesArticleComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private http = inject(HttpClient);
  private destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly content = signal<string>('');
  readonly prev = signal<GuideArticle | null>(null);
  readonly next = signal<GuideArticle | null>(null);

  ngOnInit(): void {
    // P3-10: unsubscribe from the long-lived paramMap stream on destroy.
    this.route.paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((p) => this.load(p.get('slug') ?? ''));
  }

  private load(slug: string): void {
    this.loading.set(true);
    this.notFound.set(false);
    this.prev.set(null);
    this.next.set(null);
    // Catalog membership IS the allow-list. It subsumes the old character-class
    // check (no catalog slug contains '/' or '.') AND rejects well-formed slugs
    // that simply do not exist, so no request escapes assets/guides/.
    if (!GUIDE_SLUGS.has(slug)) {
      this.loading.set(false);
      this.notFound.set(true);
      return;
    }
    const i = GUIDE_ARTICLES.findIndex(a => a.slug === slug);
    this.prev.set(i > 0 ? GUIDE_ARTICLES[i - 1] : null);
    this.next.set(i < GUIDE_ARTICLES.length - 1 ? GUIDE_ARTICLES[i + 1] : null);

    this.http.get('assets/guides/' + slug + '.html', { responseType: 'text' }).subscribe({
      next: (html) => {
        this.content.set(html);  // Angular sanitizes on [innerHTML] bind (P2-12)
        this.loading.set(false);
      },
      error: () => {
        this.notFound.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Catalog title for a slug (used by tests / future breadcrumbs). */
  titleFor(slug: string): string {
    return findGuide(slug)?.title ?? '';
  }
}
