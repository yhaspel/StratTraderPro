/** Help article viewer (M10.5 §7.3) at /help/:slug. Loads the first-party
 * static HTML from assets/help/<slug>.html and binds it to [innerHTML] so
 * Angular's default sanitizer runs (P2-12) — the styled tags (h1/h2/p/ul/a/code)
 * all survive, but any injected <script>/onerror is stripped, so a malicious
 * help file (public repo, PRs) can't run in an authed session. The slug is also
 * allow-list validated so a crafted slug can't escape assets/help/. */
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

@Component({
  selector: 'app-help-article',
  standalone: true,
  imports: [RouterLink, TranslateModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="mx-auto max-w-3xl">
      @if (loading()) {
        <p class="text-neutral-700">{{ 'common.loading' | translate }}</p>
      } @else if (notFound()) {
        <h1 class="font-heading text-[32px] font-semibold leading-tight text-ink">{{ 'help.not_found.title' | translate }}</h1>
        <p class="mt-2 text-neutral-700">{{ 'help.not_found.body' | translate }}</p>
        <a routerLink="/dashboard" class="mt-4 inline-flex text-accent-700 underline">
          {{ 'help.not_found.home' | translate }}
        </a>
      } @else {
        <div class="help-content leading-relaxed text-ink" [innerHTML]="content()"></div>
      }
    </article>
  `,
  styles: [`
    .help-content ::ng-deep h1 { font-family: var(--font-heading); font-size: 1.75rem; font-weight: 600; margin-bottom: 0.75rem; }
    .help-content ::ng-deep h2 { font-family: var(--font-heading); font-size: 1.25rem; font-weight: 600; margin: 1rem 0 0.5rem; }
    .help-content ::ng-deep p { margin-bottom: 0.75rem; }
    .help-content ::ng-deep ul { list-style: disc; padding-inline-start: 1.5rem; margin-bottom: 0.75rem; }
    .help-content ::ng-deep a { color: var(--color-accent-700); text-decoration: underline; }
    .help-content ::ng-deep code { font-family: var(--font-mono), monospace; background: var(--color-surface); padding: 0 0.25rem; border-radius: 0; }
  `],
})
export class HelpArticleComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private http = inject(HttpClient);
  private destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly content = signal<string>('');

  /** Only lowercase slugs — blocks path traversal / escaping assets/help/. */
  private static readonly SLUG_RE = /^[a-z0-9-]+$/;

  ngOnInit(): void {
    // P3-10: unsubscribe from the long-lived paramMap stream on destroy.
    this.route.paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((p) => this.load(p.get('slug') ?? ''));
  }

  private load(slug: string): void {
    this.loading.set(true);
    this.notFound.set(false);
    if (!HelpArticleComponent.SLUG_RE.test(slug)) {
      this.loading.set(false);
      this.notFound.set(true);
      return;
    }
    this.http.get(`assets/help/${slug}.html`, { responseType: 'text' }).subscribe({
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
}
