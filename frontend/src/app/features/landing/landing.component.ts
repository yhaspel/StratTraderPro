/** Public landing page (M10.5 §7.2/AC-10.5-1). A first-time visitor learns what
 * StratTraderPro does and reaches sign-in BY CLICKING. Content is honest per
 * F-13 (paper trading via Alpaca; no live/real-money claims). The environment
 * badge is driven by runtime config and only shows outside production — never
 * the old hardcoded "Platform scaffold — staging environment" string. */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { ButtonComponent } from '../shared/ui/button.component';
import { ConfigService } from '../../core/services/config.service';

@Component({
  selector: 'app-landing',
  standalone: true,
  imports: [TranslateModule, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="mx-auto max-w-5xl px-4 py-16">
      <section class="text-center">
        @if (showEnvBadge()) {
          <div class="mb-4 inline-flex items-center gap-2 rounded-md bg-primary-50 px-3 py-1 text-xs font-medium uppercase tracking-wide text-primary-700">
            {{ envLabel() }}
          </div>
        }
        <h1 class="text-4xl font-bold text-primary-900">{{ 'app.title' | translate }}</h1>
        <p class="mx-auto mt-4 max-w-2xl text-lg text-slate-600">
          {{ 'landing.hero.subtitle' | translate }}
        </p>
        <div class="mt-8 flex flex-wrap items-center justify-center gap-3">
          <app-button variant="primary" (clicked)="go('/login')">
            {{ 'landing.cta.sign_in' | translate }}
          </app-button>
          <app-button variant="secondary" (clicked)="go('/register')">
            {{ 'landing.cta.create_account' | translate }}
          </app-button>
        </div>
      </section>

      <section class="mt-16" aria-labelledby="how-it-works">
        <h2 id="how-it-works" class="text-center text-2xl font-semibold text-primary-900">
          {{ 'landing.how.title' | translate }}
        </h2>
        <ol class="mt-8 grid gap-6 md:grid-cols-4">
          @for (step of steps; track step.titleKey; let i = $index) {
            <li class="rounded-lg border border-slate-200 bg-white p-lg shadow-sm">
              <div class="text-sm font-semibold text-accent-500">{{ i + 1 }}</div>
              <h3 class="mt-1 text-base font-semibold text-slate-800">{{ step.titleKey | translate }}</h3>
              <p class="mt-1 text-sm text-slate-600">{{ step.bodyKey | translate }}</p>
            </li>
          }
        </ol>
        <p class="mt-8 text-center text-sm text-slate-500">{{ 'landing.disclaimer' | translate }}</p>
      </section>
    </main>
  `,
})
export class LandingComponent {
  private router = inject(Router);
  private config = inject(ConfigService);

  readonly steps = [
    { titleKey: 'landing.steps.alert.title', bodyKey: 'landing.steps.alert.body' },
    { titleKey: 'landing.steps.webhook.title', bodyKey: 'landing.steps.webhook.body' },
    { titleKey: 'landing.steps.risk.title', bodyKey: 'landing.steps.risk.body' },
    { titleKey: 'landing.steps.broker.title', bodyKey: 'landing.steps.broker.body' },
  ];

  showEnvBadge(): boolean {
    return this.config.sentryEnvironment !== 'production';
  }

  envLabel(): string {
    return this.config.sentryEnvironment;
  }

  go(path: string): void {
    void this.router.navigate([path]);
  }
}
