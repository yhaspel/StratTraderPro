/** /strategies/:id — pine + description previews.
 *
 * Visual layer: "Industry" design system — condensed heading, accent back
 * link, shared warn chip, code panels as font-mono on `--color-surface`.
 */
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { firstValueFrom } from 'rxjs';
import { StrategiesApi } from '../../../core/services/strategies.api';
import { Strategy } from '../../../core/models/strategies.models';
import { StatusChipComponent } from '../../shared/ui/status-chip.component';
import { ScreeningPanelComponent } from './screening-panel.component';
import { renderTradingViewDescription } from '../../../core/util/tradingview-description';

@Component({
  selector: 'app-strategies-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    TranslateModule,
    StatusChipComponent,
    ScreeningPanelComponent,
  ],
  template: `
    <div class="mx-auto max-w-4xl p-6">
      <a routerLink="/strategies"
         class="inline-block w-fit rounded-none px-1 text-[13px] text-accent-700 transition-colors hover:bg-accent-100">
        ← {{ 'strategies.detail.back' | translate }}
      </a>

      @if (loading()) {
        <p class="mt-4 text-sm text-neutral-700">{{ 'strategies.detail.loading' | translate }}</p>
      }
      @if (!loading() && strategy(); as s) {
        <h1 class="mt-2 font-heading text-[28px] font-semibold leading-[1.12] tracking-tight text-ink">{{ s.name }}</h1>
        <p class="text-sm text-neutral-700">{{ s.description_short }}</p>

        @if (!s.is_system) {
          <div class="mt-3">
            <app-status-chip tone="warn">
              ⚠ {{ 'strategies.list.untested_banner' | translate }}
            </app-status-chip>
          </div>
        }

        <!-- Actions: the guide is one click from the thing it explains. -->
        <div class="mt-4 flex flex-wrap items-center gap-3 text-[13px]">
          <a routerLink="/guides/using-a-strategy"
             class="rounded-none px-1 text-accent-700 underline transition-colors hover:bg-accent-100">
            {{ 'strategies.detail.how_to' | translate }}
          </a>
          <a routerLink="/guides/tradingview-alert-config"
             class="rounded-none px-1 text-accent-700 underline transition-colors hover:bg-accent-100">
            {{ 'strategies.detail.how_to_webhook' | translate }}
          </a>
        </div>

        <!-- Description FIRST — it is what the user came to read. The route
             existed and rendered it, but nothing in the UI linked here, so the
             description a user typed at upload time was write-only. -->
        <h2 class="mt-6 mb-2 font-heading text-lg font-semibold text-ink" id="desc-heading">{{ 'strategies.detail.description' | translate }}</h2>
        @if (filesLoading()) {
          <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
        } @else if (descHtml()) {
          <!-- TradingView BBCode ([b]/[list]/[url]/[pine]/…) rendered as visual
               cues. descHtml() escapes all text and emits a fixed tag whitelist;
               binding via [innerHTML] then runs Angular's default sanitizer
               (P2-12). The stored DESC file is never modified — display only.
               tabindex/role/aria-labelledby satisfy WCAG 2.1.1 for the scroll region. -->
          <div tabindex="0" role="region" aria-labelledby="desc-heading"
               class="tv-desc max-h-96 overflow-auto rounded-none border border-divider bg-surface p-3 text-[13px] leading-relaxed text-ink"
               [innerHTML]="descHtml()"></div>
        } @else {
          <p class="text-sm text-neutral-700">{{ 'strategies.detail.description_empty' | translate }}</p>
        }

        <!-- M16 — Screening panel sits directly under the description it is
             driven by (the [screen] block lives in that description). -->
        <app-screening-panel [strategyId]="s.id" />

        <h2 class="mt-6 mb-2 font-heading text-lg font-semibold text-ink" id="tmpl-heading">{{ 'strategies.detail.webhook_template' | translate }}</h2>
        <p class="mb-2 text-[13px] text-neutral-700">{{ 'strategies.detail.webhook_template_hint' | translate }}</p>
        @if (filesLoading()) {
          <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
        } @else if (templateText()) {
          <pre tabindex="0" role="region" aria-labelledby="tmpl-heading"
               class="max-h-96 overflow-auto whitespace-pre-wrap rounded-none border border-divider bg-surface p-3 font-mono text-xs text-ink"><code>{{ templateText() }}</code></pre>
        } @else {
          <p class="text-sm text-neutral-700">{{ 'strategies.detail.webhook_template_empty' | translate }}</p>
        }

        <h2 class="mt-6 mb-2 font-heading text-lg font-semibold text-ink" id="pine-heading">{{ 'strategies.detail.pine' | translate }}</h2>
        <pre tabindex="0" role="region" aria-labelledby="pine-heading"
             class="max-h-96 overflow-auto whitespace-pre-wrap rounded-none border border-divider bg-surface p-3 font-mono text-xs text-ink"><code>{{ pineText() }}</code></pre>
      }
      @if (!loading() && !strategy()) {
        <div class="mt-4 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
          {{ 'strategies.detail.not_found' | translate }}
        </div>
      }
    </div>
  `,
  // Styling for the [innerHTML] description. ::ng-deep is required because the
  // rendered nodes are not view-encapsulated (same approach as guides
  // .help-content). Tokens come from src/styles/tokens.css.
  styles: [`
    .tv-desc ::ng-deep strong { font-weight: 600; }
    .tv-desc ::ng-deep em { font-style: italic; }
    .tv-desc ::ng-deep s { text-decoration: line-through; }
    .tv-desc ::ng-deep a { color: var(--color-accent-700); text-decoration: underline; }
    .tv-desc ::ng-deep a:hover { background: var(--color-accent-100); }
    .tv-desc ::ng-deep ul { list-style: disc; padding-inline-start: 1.5rem; margin: 0.5rem 0; }
    .tv-desc ::ng-deep ol { list-style: decimal; padding-inline-start: 1.5rem; margin: 0.5rem 0; }
    .tv-desc ::ng-deep li { margin-bottom: 0.25rem; }
    .tv-desc ::ng-deep blockquote { border-inline-start: 2px solid var(--color-divider); padding-inline-start: 0.75rem; margin: 0.5rem 0; color: var(--color-neutral-700); font-style: italic; }
    .tv-desc ::ng-deep pre { background: var(--color-surface); border: 1px solid var(--color-divider); padding: 0.75rem; overflow-x: auto; font-size: 0.8rem; margin: 0.5rem 0; }
    .tv-desc ::ng-deep pre code { font-family: var(--font-mono), monospace; background: transparent; padding: 0; white-space: pre; }
    .tv-desc ::ng-deep img { display: block; max-width: 100%; height: auto; border: 1px solid var(--color-divider); margin: 0.5rem 0; }
  `],
})
export class StrategiesDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private api = inject(StrategiesApi);

  loading = signal(true);
  /** File bodies load after the route resolves; the panels say "loading"
   *  rather than falsely reporting "no description" while they are in flight. */
  filesLoading = signal(true);
  strategy = signal<Strategy | null>(null);
  pineText = signal<string>('');
  descText = signal<string>('');
  templateText = signal<string>('');

  /** TradingView BBCode → safe HTML, recomputed when descText() changes.
   *  Display-only; the stored DESC file is never touched. */
  descHtml = computed(() => renderTradingViewDescription(this.descText()));

  async ngOnInit(): Promise<void> {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) { this.loading.set(false); this.filesLoading.set(false); return; }
    try {
      const res = await firstValueFrom(this.api.get(id));
      if (res.error) { this.loading.set(false); this.filesLoading.set(false); return; }
      this.strategy.set(res.data!);
      // Lazy-load file bytes — don't block the route on them.
      void this._loadFiles(id);
    } finally {
      this.loading.set(false);
    }
  }

  private async _loadFiles(id: string): Promise<void> {
    // Settled, not all-or-nothing: a missing WEBHOOK_TEMPLATE must not blank
    // out the description too (Promise.all rejects the whole batch).
    const [pine, desc, tmpl] = await Promise.allSettled([
      firstValueFrom(this.api.download(id, 'PINE')),
      firstValueFrom(this.api.download(id, 'DESC')),
      firstValueFrom(this.api.download(id, 'WEBHOOK_TEMPLATE')),
    ]);
    this.pineText.set(await this._text(pine));
    this.descText.set(await this._text(desc));
    this.templateText.set(this._pretty(await this._text(tmpl)));
    this.filesLoading.set(false);
  }

  private async _text(r: PromiseSettledResult<Blob>): Promise<string> {
    if (r.status !== 'fulfilled') { return ''; }
    try {
      return (await r.value.text()).trim();
    } catch {
      return '';
    }
  }

  /** Pretty-print the payload template when it is valid JSON; otherwise show
   *  the raw bytes rather than swallowing them. */
  private _pretty(raw: string): string {
    if (!raw) { return ''; }
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }
}
