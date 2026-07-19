/**
 * <app-regime-history> — a dependency-free ~90-day regime band ("Industry"
 * restyle).
 *
 * Renders the recent regime history as a horizontal strip of colored segments
 * (regime palette fills), one per observation, oldest→newest. Each segment
 * carries a native tooltip (date + label). No chart library — just flex divs
 * colored by label, plus a square-swatch legend so meaning is not color-only.
 */
import { Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { RegimeLabel, RegimeObservation } from '../../core/models/regime.models';
import { RegimeFacade } from '../../abstraction/facades/regime.facade';

const MAX_SEGMENTS = 90;

@Component({
  selector: 'app-regime-history',
  standalone: true,
  imports: [CommonModule, TranslateModule],
  template: `
    <div>
      <div class="mb-2 text-[10px] font-medium uppercase tracking-[.1em] text-accent-700">
        {{ 'regime.history' | translate }}
      </div>
      @if (series().length === 0) {
        <p class="text-xs text-neutral-700">{{ 'regime.no_data' | translate }}</p>
      } @else {
        <div class="flex h-5 w-full gap-px overflow-hidden border border-divider"
             role="img" [attr.aria-label]="ariaSummary()">
          @for (o of series(); track o.ts) {
            <div class="min-w-px flex-1" [ngClass]="barClass(o.label)" [title]="segTitle(o)"></div>
          }
        </div>
        <!-- Legend: color → regime label, so meaning is not color-only. -->
        <ul class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-neutral-700" aria-hidden="true">
          @for (l of legendLabels(); track l) {
            <li class="inline-flex items-center gap-[5px]">
              <span class="inline-block h-[9px] w-[9px]" [ngClass]="barClass(l)"></span>
              {{ 'regime.label.' + l | translate }}
            </li>
          }
        </ul>
      }
    </div>
  `,
})
export class RegimeHistoryComponent {
  private facade = inject(RegimeFacade);
  private translate = inject(TranslateService);

  /** Most-recent-first from the API; show oldest→newest, capped to ~90. */
  readonly series = computed<RegimeObservation[]>(() =>
    this.facade.history().slice(0, MAX_SEGMENTS).reverse(),
  );

  /** Distinct regime labels present, in first-seen order — drives the legend. */
  readonly legendLabels = computed<RegimeLabel[]>(() => {
    const seen: RegimeLabel[] = [];
    for (const o of this.series()) {
      if (!seen.includes(o.label)) { seen.push(o.label); }
    }
    return seen;
  });

  /** Accessible summary of the color-coded band (role="img" alt text). */
  readonly ariaSummary = computed<string>(() => {
    const s = this.series();
    if (s.length === 0) { return this.translate.instant('regime.history'); }
    const counts = new Map<RegimeLabel, number>();
    for (const o of s) { counts.set(o.label, (counts.get(o.label) ?? 0) + 1); }
    const parts = [...counts.entries()].map(
      ([label, n]) => `${n} ${this.translate.instant('regime.label.' + label)}`,
    );
    const current = this.translate.instant('regime.label.' + s[s.length - 1].label);
    return `${s.length}-day market regime history: ${parts.join(', ')}. Current regime: ${current}.`;
  });

  barClass(label: RegimeLabel): string {
    switch (label) {
      case 'BULL': return 'bg-regime-bull';
      case 'CHOP': return 'bg-regime-chop';
      case 'BEAR': return 'bg-regime-bear';
      case 'CRISIS': return 'bg-regime-crisis';
      default: return 'bg-regime-neutral';
    }
  }

  segTitle(o: RegimeObservation): string {
    const date = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' }).format(new Date(o.ts));
    return `${date} · ${this.translate.instant('regime.label.' + o.label)}`;
  }
}
