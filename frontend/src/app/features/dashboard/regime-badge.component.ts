/**
 * <app-regime-badge> — M06 current market regime badge.
 *
 * Shows the current regime label (colored by label), a hover/click popover of
 * the top-5 contributing features with their z-scores, a degraded ("rule-based
 * only") warning chip when the model is degraded (AC-06-8), and the recent
 * regime history band. Reads everything from the RegimeFacade signals; the
 * dashboard triggers the loads on init.
 */
import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { RegimeFacade } from '../../abstraction/facades/regime.facade';
import { RegimeHistoryComponent } from './regime-history.component';
import { HelpLinkComponent } from '../shared/ui/help-link.component';

@Component({
  selector: 'app-regime-badge',
  standalone: true,
  imports: [CommonModule, TranslateModule, RegimeHistoryComponent, HelpLinkComponent],
  template: `
    <section class="rounded border border-gray-200 p-4 space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold">
          {{ 'regime.title' | translate }}<app-help-link slug="regime-badge" />
        </h2>
      </div>

      @if (facade.current(); as o) {
        <div class="flex flex-wrap items-center gap-3">
          <!-- Regime label badge — color by label. -->
          <div class="relative"
               (mouseenter)="open.set(true)"
               (mouseleave)="open.set(false)">
            <button type="button"
                    class="inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold"
                    [ngClass]="labelClass(o.label)"
                    (click)="open.set(!open())">
              @switch (o.label) {
                @case ('BULL') { {{ 'regime.label.BULL' | translate }} }
                @case ('CHOP') { {{ 'regime.label.CHOP' | translate }} }
                @case ('BEAR') { {{ 'regime.label.BEAR' | translate }} }
                @case ('CRISIS') { {{ 'regime.label.CRISIS' | translate }} }
                @default { {{ 'regime.label.NEUTRAL' | translate }} }
              }
            </button>

            <!-- Top-5 contributing features popover. -->
            @if (open() && o.top_features.length > 0) {
              <div class="absolute left-0 z-10 mt-2 w-64 rounded border border-gray-200 bg-white p-3 shadow-lg">
                <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  {{ 'regime.top_features' | translate }}
                </div>
                <ul class="space-y-1">
                  @for (f of o.top_features.slice(0, 5); track f.name) {
                    <li class="flex items-center justify-between text-sm">
                      <span class="text-gray-700">{{ featureLabel(f.name) }}</span>
                      <span class="font-mono"
                            [class.text-green-700]="f.z >= 0"
                            [class.text-red-700]="f.z < 0">{{ fmtZ(f.z) }}</span>
                    </li>
                  }
                </ul>
              </div>
            }
          </div>

          <!-- Rule-based bucket, for context. -->
          <span class="text-sm text-gray-500">
            @switch (o.rule_bucket) {
              @case ('RISK_ON') { {{ 'regime.rule.RISK_ON' | translate }} }
              @case ('RISK_OFF') { {{ 'regime.rule.RISK_OFF' | translate }} }
              @case ('PANIC') { {{ 'regime.rule.PANIC' | translate }} }
              @default { {{ 'regime.rule.NEUTRAL' | translate }} }
            }
          </span>

          <!-- Degraded warning chip (AC-06-8). -->
          @if (o.model.degraded) {
            <span class="inline-flex items-center rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
                  role="status">
              {{ 'regime.degraded' | translate }}
            </span>
          }
        </div>
      } @else if (facade.loading()) {
        <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
      } @else {
        <p class="text-sm text-gray-500">{{ 'regime.no_data' | translate }}</p>
      }

      <!-- ~90-day regime band. -->
      <app-regime-history />
    </section>
  `,
})
export class RegimeBadgeComponent {
  facade = inject(RegimeFacade);
  private translate = inject(TranslateService);

  readonly open = signal(false);

  labelClass(label: string): string {
    switch (label) {
      case 'BULL': return 'bg-green-100 text-green-800';
      case 'CHOP': return 'bg-amber-100 text-amber-800';
      case 'BEAR': return 'bg-orange-100 text-orange-800';
      case 'CRISIS': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  }

  /** i18n label for a feature; falls back to the raw name when no key exists. */
  featureLabel(name: string): string {
    const key = `regime.feature.${name}`;
    const label = this.translate.instant(key);
    return label === key ? name : label;
  }

  fmtZ(z: number): string {
    return new Intl.NumberFormat('en-US', {
      signDisplay: 'always',
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    }).format(z);
  }
}
