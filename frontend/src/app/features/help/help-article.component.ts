/** Help article viewer (M10.5 §7.3) at /help/:slug. Loads the first-party
 * static HTML from assets/help/<slug>.html and renders it sanitized. The slug
 * is validated against a strict allow-list pattern so a crafted slug can never
 * escape the help directory (§11) — bypassSecurityTrustHtml is only ever used
 * on these vetted first-party files. Unknown slug → inline not-found. */
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { TranslateModule } from '@ngx-translate/core';

@Component({
  selector: 'app-help-article',
  standalone: true,
  imports: [RouterLink, TranslateModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="mx-auto max-w-3xl">
      @if (loading()) {
        <p class="text-slate-500">{{ 'common.loading' | translate }}</p>
      } @else if (notFound()) {
        <h1 class="text-2xl font-semibold text-slate-800">{{ 'help.not_found.title' | translate }}</h1>
        <p class="mt-2 text-slate-600">{{ 'help.not_found.body' | translate }}</p>
        <a routerLink="/dashboard" class="mt-4 inline-flex text-primary-700 underline">
          {{ 'help.not_found.home' | translate }}
        </a>
      } @else {
        <div class="help-content leading-relaxed text-slate-700" [innerHTML]="content()"></div>
      }
    </article>
  `,
  styles: [`
    .help-content ::ng-deep h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.75rem; }
    .help-content ::ng-deep h2 { font-size: 1.15rem; font-weight: 600; margin: 1rem 0 0.5rem; }
    .help-content ::ng-deep p { margin-bottom: 0.75rem; }
    .help-content ::ng-deep ul { list-style: disc; padding-inline-start: 1.5rem; margin-bottom: 0.75rem; }
    .help-content ::ng-deep a { color: var(--color-primary-700); text-decoration: underline; }
    .help-content ::ng-deep code { font-family: monospace; background: #f1f5f9; padding: 0 0.25rem; border-radius: 0.25rem; }
  `],
})
export class HelpArticleComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private http = inject(HttpClient);
  private sanitizer = inject(DomSanitizer);

  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly content = signal<SafeHtml>('');

  /** Only lowercase slugs — blocks path traversal / escaping assets/help/. */
  private static readonly SLUG_RE = /^[a-z0-9-]+$/;

  ngOnInit(): void {
    this.route.paramMap.subscribe((p) => this.load(p.get('slug') ?? ''));
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
        this.content.set(this.sanitizer.bypassSecurityTrustHtml(html));
        this.loading.set(false);
      },
      error: () => {
        this.notFound.set(true);
        this.loading.set(false);
      },
    });
  }
}
