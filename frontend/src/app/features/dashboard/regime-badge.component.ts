/**
 * <app-regime-badge> — M06 current market regime badge ("Industry" restyle).
 *
 * Shows the current regime as a status chip (tone by label via the shared
 * STATUS_CHIP_TONE map), a hover/click popover of the top-5 contributing
 * features with their z-scores, a degraded ("rule-based only") warn chip when
 * the model is degraded (AC-06-8), and the recent regime history band. Reads
 * everything from the RegimeFacade signals; the dashboard triggers the loads
 * on init.
 */
import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { RegimeFacade } from '../../abstraction/facades/regime.facade';
import { RegimeHistoryComponent } from './regime-history.component';
import { HelpLinkComponent } from '../shared/ui/help-link.component';
import { CardComponent } from '../shared/ui/card.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

@Component({
  selector: 'app-regime-badge',
  standalone: true,
  imports: [
    CommonModule, TranslateModule, RegimeHistoryComponent, HelpLinkComponent,
    CardComponent, StatusChipComponent,
  ],
  template: `
    <app-card>
      <div class="space-y-3">
        <h2 class="font-heading text-[13px] font-semibold uppercase tracking-[.08em] text-neutral-700">
          {{ 'regime.title' | translate }}<app-help-link slug="regime-badge" />
        </h2>

        @if (facade.current(); as o) {
          <div class="flex flex-wrap items-center gap-3">
            <!-- Regime label chip — tone by label; popover trigger. -->
            <div class="relative"
                 (mouseenter)="open.set(true)"
                 (mouseleave)="open.set(false)">
              <button type="button"
                      class="block cursor-pointer rounded-none border-0 bg-transparent p-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      [attr.aria-expanded]="open()"
                      (click)="open.set(!open())">
                <app-status-chip [status]="o.label">
                  @switch (o.label) {
                    @case ('BULL') { {{ 'regime.label.BULL' | translate }} }
                    @case ('CHOP') { {{ 'regime.label.CHOP' | translate }} }
                    @case ('BEAR') { {{ 'regime.label.BEAR' | translate }} }
                    @case ('CRISIS') { {{ 'regime.label.CRISIS' | translate }} }
                    @default { {{ 'regime.label.NEUTRAL' | translate }} }
                  }
                </app-status-chip>
              </button>

              <!-- Top-5 contributing features popover. -->
              @if (open() && o.top_features.length > 0) {
                <div class="absolute left-0 z-10 mt-2 w-64 rounded-none border border-divider bg-bg p-3 shadow-lg">
                  <div class="mb-2 text-[10px] font-medium uppercase tracking-[.1em] text-accent-700">
                    {{ 'regime.top_features' | translate }}
                  </div>
                  <ul class="space-y-1">
                    @for (f of o.top_features.slice(0, 5); track f.name) {
                      <li class="flex items-center justify-between text-sm">
                        <span class="text-neutral-700">{{ featureLabel(f.name) }}</span>
                        <span class="font-mono tabular-nums text-ink">{{ fmtZ(f.z) }}</span>
                      </li>
                    }
                  </ul>
                </div>
              }
            </div>

            <!-- Rule-based bucket, for context. -->
            <span class="text-[13px] text-neutral-600">
              @switch (o.rule_bucket) {
                @case ('RISK_ON') { {{ 'regime.rule.RISK_ON' | translate }} }
                @case ('RISK_OFF') { {{ 'regime.rule.RISK_OFF' | translate }} }
                @case ('PANIC') { {{ 'regime.rule.PANIC' | translate }} }
                @default { {{ 'regime.rule.NEUTRAL' | translate }} }
              }
            </span>

            <!-- Degraded warning chip (AC-06-8). -->
            @if (o.model.degraded) {
              <app-status-chip tone="warn" role="status">
                <span aria-hidden="true">⚠&nbsp;</span>{{ 'regime.degraded' | translate }}
              </app-status-chip>
            }
          </div>
        } @else if (facade.loading()) {
          <p class="text-sm text-neutral-600">{{ 'common.loading' | translate }}</p>
        } @else {
          <p class="text-sm text-neutral-600">{{ 'regime.no_data' | translate }}</p>
        }

        <!-- ~90-day regime band. -->
        <app-regime-history />
      </div>
    </app-card>
  `,
})
export class RegimeBadgeComponent {
  facade = inject(RegimeFacade);
  private translate = inject(TranslateService);

  readonly open = signal(false);

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
