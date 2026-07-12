/** Help index (M10.5 §7.3/AC-10.5-6) at /help — links every first-party help
 * article so NONE is orphaned. Each entry opens the article at /help/:slug. The
 * slug list mirrors the files in assets/help/ (13 confirmed 2026-07-12). */
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

interface Article {
  slug: string;
  title: string;
}

@Component({
  selector: 'app-help-index',
  standalone: true,
  imports: [RouterLink, TranslateModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="mx-auto max-w-3xl">
      <h1 class="text-2xl font-bold text-primary-900">{{ 'help.index.title' | translate }}</h1>
      <p class="mt-1 text-sm text-slate-600">{{ 'help.index.subtitle' | translate }}</p>
      <ul class="mt-md grid gap-2 sm:grid-cols-2">
        @for (a of articles; track a.slug) {
          <li>
            <a
              [routerLink]="['/help', a.slug]"
              class="block rounded-md border border-slate-200 px-3 py-2 text-sm text-primary-700 hover:bg-slate-50">
              {{ a.title }}
            </a>
          </li>
        }
      </ul>
    </div>
  `,
})
export class HelpIndexComponent {
  // Titles are plain strings (help articles are English-only static HTML).
  readonly articles: Article[] = [
    { slug: 'mfa', title: 'Two-factor authentication' },
    { slug: 'alpaca-paper-connect', title: 'Connecting Alpaca paper' },
    { slug: 'tradestation-connect', title: 'Connecting TradeStation' },
    { slug: 'strategy-upload', title: 'Uploading a strategy' },
    { slug: 'tradingview-alert-config', title: 'Configuring a TradingView alert' },
    { slug: 'orders-page', title: 'The orders page' },
    { slug: 'risk-profile', title: 'Your risk profile' },
    { slug: 'kill-switch', title: 'Kill switches' },
    { slug: 'regime-badge', title: 'The market-regime badge' },
    { slug: 'sentiment', title: 'Market sentiment' },
    { slug: 'running-your-first-backtest', title: 'Running your first backtest' },
    { slug: 'reading-the-tearsheet', title: 'Reading the tearsheet' },
    { slug: 'interpreting-pbo', title: 'Interpreting PBO' },
  ];
}
