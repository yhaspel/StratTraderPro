/** Getting-started checklist (M10.5 §7.3/AC-10.5-5). Renders the four frozen
 * onboarding steps with REAL state from OnboardingFacade; each incomplete step
 * deep-links to the screen that resolves it. Shown as the dashboard empty state.
 * MFA is step 0 — every dashboard data endpoint 403s until it is enrolled. */
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { OnboardingFacade } from '../../../abstraction/facades/onboarding.facade';
import { OnboardingStatus } from '../../../core/models/onboarding.models';

interface StepDef {
  key: keyof Omit<OnboardingStatus, 'complete'>;
  labelKey: string;
  link: string;
  ctaKey: string;
}

@Component({
  selector: 'app-onboarding-checklist',
  standalone: true,
  imports: [RouterLink, TranslateModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="rounded-lg border border-slate-200 bg-white p-lg shadow-sm" aria-labelledby="ob-title">
      <h2 id="ob-title" class="text-lg font-semibold text-primary-900">{{ 'onboarding.title' | translate }}</h2>
      <p class="mt-1 text-sm text-slate-600">{{ 'onboarding.subtitle' | translate }}</p>
      <ol class="mt-md space-y-2">
        @for (step of steps(); track step.key; let i = $index) {
          <li class="flex items-center justify-between gap-md rounded-md border border-slate-100 px-3 py-2">
            <span class="flex items-center gap-2">
              <span
                class="flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold"
                [class.bg-success-500]="step.done"
                [class.text-white]="step.done"
                [class.bg-slate-100]="!step.done"
                [class.text-slate-500]="!step.done"
                aria-hidden="true">{{ step.done ? '✓' : (i + 1) }}</span>
              <span class="text-sm" [class.text-slate-400]="step.done" [class.line-through]="step.done">
                {{ step.labelKey | translate }}
              </span>
            </span>
            @if (step.done) {
              <span class="text-xs font-medium text-success-500">{{ 'onboarding.done' | translate }}</span>
            } @else {
              <a [routerLink]="step.link" class="text-sm font-medium text-primary-700 hover:underline">
                {{ step.ctaKey | translate }}
              </a>
            }
          </li>
        }
      </ol>
      @if (showFillHint()) {
        <p class="mt-md text-xs text-slate-500">{{ 'onboarding.fill_hint' | translate }}</p>
      }
    </section>
  `,
})
export class OnboardingChecklistComponent {
  private onboarding = inject(OnboardingFacade);

  private readonly defs: StepDef[] = [
    { key: 'mfa_enrolled', labelKey: 'onboarding.steps.mfa', link: '/settings/security/mfa/setup', ctaKey: 'onboarding.cta.enable' },
    { key: 'broker_connected', labelKey: 'onboarding.steps.broker', link: '/settings/brokers', ctaKey: 'onboarding.cta.connect' },
    { key: 'strategy_ready', labelKey: 'onboarding.steps.strategy', link: '/strategies', ctaKey: 'onboarding.cta.add' },
    { key: 'first_fill_seen', labelKey: 'onboarding.steps.fill', link: '/dashboard', ctaKey: 'onboarding.cta.view' },
  ];

  readonly steps = computed(() => {
    const s = this.onboarding.status();
    if (!s) { return []; }
    return this.defs.map((d) => ({ ...d, done: s[d.key] }));
  });

  showFillHint(): boolean {
    const s = this.onboarding.status();
    return !!s && !s.first_fill_seen && s.broker_connected && s.strategy_ready;
  }
}
