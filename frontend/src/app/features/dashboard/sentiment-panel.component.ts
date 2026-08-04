/**
 * <app-sentiment-panel> — M07 market news-sentiment panel ("Industry" restyle).
 *
 * Shows the current market sentiment as a signed mono value in [-1, +1]
 * colored by sign (up / muted neutral band / down), a dependency-free inline
 * SVG spark line of the polarity history (mirrors the regime-history band), a
 * "rule-based / LLM degraded" warn chip when the sentiment model is degraded,
 * and a "Recent impactful news" feed (top articles by |impact|). Reads
 * everything from the SentimentFacade signals; the dashboard triggers the
 * loads on init.
 */
import { Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule } from '@ngx-translate/core';
import { SentimentFacade } from '../../abstraction/facades/sentiment.facade';
import { SentimentArticle, SentimentScore } from '../../core/models/sentiment.models';
import { HelpLinkComponent } from '../shared/ui/help-link.component';
import { CardComponent } from '../shared/ui/card.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

/** Below this magnitude a polarity reads as neutral rather than pos/neg. */
const NEUTRAL_BAND = 0.05;
/** How many recent impactful articles to surface. */
const TOP_ARTICLES = 8;
/** Spark line viewBox geometry (mockup: 150×40). */
const SPARK_W = 150;
const SPARK_H = 40;
const SPARK_PAD = 4;

@Component({
  selector: 'app-sentiment-panel',
  standalone: true,
  imports: [CommonModule, TranslateModule, HelpLinkComponent, CardComponent, StatusChipComponent],
  template: `
    <app-card>
      <div class="space-y-3">
        <h2 class="font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
          {{ 'sentiment.title' | translate }}<app-help-link slug="sentiment" />
        </h2>

        @if (market()?.current; as c) {
          <div class="flex flex-wrap items-center gap-5">
            <!-- Current market polarity — signed mono, colored by sign. -->
            <div class="flex flex-col">
              <span class="text-[11px] font-medium uppercase tracking-wide text-neutral-700">
                {{ 'sentiment.market' | translate }}
              </span>
              <span class="font-mono text-[28px] font-semibold tabular-nums" [ngClass]="polarityTextClass(c.polarity)">
                {{ fmtPolarity(c.polarity) }}
              </span>
            </div>

            <!-- Polarity history spark line. -->
            @if (sparkPoints(); as pts) {
              <svg class="h-10 w-[150px]" [attr.viewBox]="'0 0 ' + SPARK_W + ' ' + SPARK_H"
                   preserveAspectRatio="none" role="img"
                   [attr.aria-label]="'sentiment.market' | translate">
                <line [attr.x1]="0" [attr.y1]="midY" [attr.x2]="SPARK_W" [attr.y2]="midY"
                      stroke="currentColor" class="text-divider" stroke-width="1" />
                <polyline [attr.points]="pts" fill="none" stroke="currentColor" stroke-width="1.5"
                          stroke-linejoin="round" stroke-linecap="round"
                          [ngClass]="polarityTextClass(c.polarity)" />
              </svg>
            }

            <!-- Degraded chip (rule-based / LLM degraded). -->
            @if (degraded()) {
              <app-status-chip tone="warn" role="status">
                {{ 'sentiment.degraded' | translate }}
              </app-status-chip>
            }
          </div>
        } @else if (loading()) {
          <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
        } @else {
          <p class="text-sm text-neutral-700">{{ 'sentiment.no_data' | translate }}</p>
        }

        <!-- Recent impactful news. -->
        <div>
          <div class="pb-1.5 text-[10px] font-medium uppercase tracking-[.1em] text-accent-700">
            {{ 'sentiment.recent_news' | translate }}
          </div>
          @if (topArticles().length === 0) {
            <p class="text-xs text-neutral-700">{{ 'sentiment.no_data' | translate }}</p>
          } @else {
            <ul>
              @for (a of topArticles(); track a.id) {
                <li class="flex items-center gap-2.5 border-t border-divider py-[7px] text-[13px]">
                  <span class="font-mono text-base leading-none" [ngClass]="polarityTextClass(a.polarity)"
                        [attr.aria-label]="polarityLabelKey(a.polarity) | translate">
                    {{ polarityArrow(a.polarity) }}
                  </span>
                  <a [href]="a.url" target="_blank" rel="noopener"
                     class="flex-1 truncate text-ink hover:underline">{{ a.title }}</a>
                  <span class="shrink-0 text-[11px] text-neutral-700">{{ a.source }}</span>
                  @if (a.impact != null) {
                    <span class="shrink-0 font-mono text-[11px] tabular-nums text-neutral-700">
                      {{ 'sentiment.impact' | translate }} {{ fmtImpact(a.impact) }}
                    </span>
                  }
                </li>
              }
            </ul>
          }
        </div>
      </div>
    </app-card>
  `,
})
export class SentimentPanelComponent {
  facade = inject(SentimentFacade);

  readonly market = this.facade.market;
  readonly degraded = this.facade.degraded;
  readonly loading = this.facade.loading;

  readonly SPARK_W = SPARK_W;
  readonly SPARK_H = SPARK_H;
  readonly midY = SPARK_H / 2;

  /** Articles ranked by |impact| (nulls last), capped to the top few. */
  readonly topArticles = computed<SentimentArticle[]>(() =>
    [...this.facade.articles()]
      .sort((a, b) => this._absImpact(b) - this._absImpact(a))
      .slice(0, TOP_ARTICLES),
  );

  /** History polarity as an SVG polyline `points` string, oldest→newest.
   *  Returns null when there are too few points to draw a line. */
  readonly sparkPoints = computed<string | null>(() => {
    const series = (this.market()?.history ?? []).slice().reverse();
    if (series.length < 2) { return null; }
    const span = SPARK_H - 2 * SPARK_PAD;
    const step = SPARK_W / (series.length - 1);
    return series
      .map((s: SentimentScore, i: number) => {
        const p = Math.max(-1, Math.min(1, s.polarity));
        const x = i * step;
        const y = SPARK_PAD + ((1 - p) / 2) * span;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  });

  polarityTextClass(polarity: number | null): string {
    const p = polarity ?? 0;
    if (p > NEUTRAL_BAND) { return 'text-up'; }
    if (p < -NEUTRAL_BAND) { return 'text-down'; }
    return 'text-neutral-700';
  }

  polarityArrow(polarity: number | null): string {
    const p = polarity ?? 0;
    if (p > NEUTRAL_BAND) { return '▲'; }
    if (p < -NEUTRAL_BAND) { return '▼'; }
    return '•';
  }

  polarityLabelKey(polarity: number | null): string {
    const p = polarity ?? 0;
    if (p > NEUTRAL_BAND) { return 'sentiment.positive'; }
    if (p < -NEUTRAL_BAND) { return 'sentiment.negative'; }
    return 'sentiment.neutral';
  }

  fmtPolarity(polarity: number): string {
    return new Intl.NumberFormat('en-US', {
      signDisplay: 'always',
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    }).format(polarity);
  }

  fmtImpact(impact: number): string {
    return new Intl.NumberFormat('en-US', {
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    }).format(impact);
  }

  private _absImpact(a: SentimentArticle): number {
    return a.impact == null ? -1 : Math.abs(a.impact);
  }
}
