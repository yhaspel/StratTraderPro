/** Public landing page (M10.5 §7.2/AC-10.5-1). A first-time visitor learns what
 * StratTraderPro does and reaches sign-in BY CLICKING. Content is honest per
 * F-13 (paper trading via Alpaca; no live/real-money claims). The environment
 * badge is driven by runtime config and only shows outside production — never
 * the old hardcoded "Platform scaffold — staging environment" string. */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';
import { ConfigService } from '../../core/services/config.service';

@Component({
  selector: 'app-landing',
  standalone: true,
  imports: [TranslateModule, ButtonComponent, CardComponent, StatusChipComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="border-b border-divider">
      <div class="mx-auto flex w-full max-w-[1120px] items-center justify-between px-6 py-3">
        <span class="inline-flex items-center gap-[9px] font-heading text-lg font-semibold text-ink">
          <span aria-hidden="true"
                class="inline-flex h-6 w-6 items-end justify-center gap-[2px] border border-ink px-1 pb-[3px] pt-1">
            <span class="h-[7px] w-[3px] bg-accent"></span>
            <span class="h-[11px] w-[3px] bg-accent"></span>
            <span class="h-[5px] w-[3px] bg-accent-400"></span>
          </span>
          {{ 'app.title' | translate }}
        </span>
        <app-button variant="secondary" (clicked)="go('/login')">
          {{ 'landing.cta.sign_in' | translate }}
        </app-button>
      </div>
    </header>

    <main class="mx-auto flex w-full max-w-[1120px] flex-col gap-16 px-8 pb-24 pt-16">
      <section class="flex flex-col items-center gap-5 text-center">
        @if (showEnvBadge()) {
          <app-status-chip tone="info"><span class="uppercase">{{ envLabel() }}</span></app-status-chip>
        }
        <app-status-chip tone="outline">
          <span class="font-mono tracking-[0.1em]">{{ 'landing.hero.tag' | translate }}</span>
        </app-status-chip>
        <h1 class="m-0 max-w-[800px] font-heading text-[56px] font-semibold leading-[1.05] text-ink">
          {{ 'landing.hero.title_pre' | translate }}
          <span class="text-accent-700">{{ 'landing.hero.title_em' | translate }}</span>
          {{ 'landing.hero.title_post' | translate }}
        </h1>
        <p class="m-0 max-w-[620px] text-[17px] leading-relaxed text-neutral-700">
          {{ 'landing.hero.subtitle' | translate }}
        </p>
        <div class="mt-2 flex flex-wrap items-center justify-center gap-3.5">
          <app-button variant="primary" [frame]="true"
                      class="[&>button]:px-[22px] [&>button]:py-[10px] [&>button]:text-[15px]"
                      (clicked)="go('/login')">
            {{ 'landing.cta.sign_in' | translate }}
          </app-button>
          <app-button variant="secondary"
                      class="[&>button]:px-[22px] [&>button]:py-[10px] [&>button]:text-[15px]"
                      (clicked)="go('/register')">
            {{ 'landing.cta.create_account' | translate }}
          </app-button>
        </div>
      </section>

      <section class="flex flex-col gap-6" aria-labelledby="how-it-works">
        <h2 id="how-it-works"
            class="m-0 text-center font-heading text-sm font-semibold uppercase tracking-[0.08em] text-neutral-700">
          {{ 'landing.how.title' | translate }}
        </h2>
        <ol class="m-0 grid list-none gap-3.5 p-0 md:grid-cols-4">
          @for (step of steps; track step.titleKey; let i = $index) {
            <li>
              <app-card class="block h-full">
                <div class="flex flex-col gap-2">
                  <span class="font-mono text-xs font-semibold text-accent-700">0{{ i + 1 }}</span>
                  <h3 class="m-0 font-heading text-base font-semibold text-ink">{{ step.titleKey | translate }}</h3>
                  <p class="m-0 text-[13px] leading-relaxed text-neutral-700">{{ step.bodyKey | translate }}</p>
                </div>
              </app-card>
            </li>
          }
        </ol>
        <p class="mx-auto max-w-[640px] text-center text-xs leading-relaxed text-neutral-700">
          {{ 'landing.disclaimer' | translate }}
        </p>
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
