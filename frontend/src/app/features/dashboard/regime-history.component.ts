/**
 * <app-regime-history> — a dependency-free ~90-day regime band.
 *
 * Renders the recent regime history as a horizontal strip of colored segments,
 * one per observation, oldest→newest. Each segment carries a native tooltip
 * (date + label). No chart library — just flex divs colored by label.
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
      <div class="mb-1 text-xs font-medium text-gray-500">{{ 'regime.history' | translate }}</div>
      @if (series().length === 0) {
        <p class="text-xs text-gray-400">{{ 'regime.no_data' | translate }}</p>
      } @else {
        <div class="flex h-6 w-full gap-px overflow-hidden rounded border border-gray-200">
          @for (o of series(); track o.ts) {
            <div class="min-w-px flex-1" [ngClass]="barClass(o.label)" [title]="segTitle(o)"></div>
          }
        </div>
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

  barClass(label: RegimeLabel): string {
    switch (label) {
      case 'BULL': return 'bg-green-500';
      case 'CHOP': return 'bg-amber-400';
      case 'BEAR': return 'bg-orange-500';
      case 'CRISIS': return 'bg-red-600';
      default: return 'bg-gray-400';
    }
  }

  segTitle(o: RegimeObservation): string {
    const date = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' }).format(new Date(o.ts));
    return `${date} · ${this.translate.instant('regime.label.' + o.label)}`;
  }
}
