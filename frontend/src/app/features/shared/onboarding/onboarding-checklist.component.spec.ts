import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { OnboardingChecklistComponent } from './onboarding-checklist.component';
import { OnboardingFacade } from '../../../abstraction/facades/onboarding.facade';
import { OnboardingStatus } from '../../../core/models/onboarding.models';

describe('OnboardingChecklistComponent', () => {
  function setup(status: OnboardingStatus | null) {
    TestBed.configureTestingModule({
      imports: [OnboardingChecklistComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        { provide: OnboardingFacade, useValue: { status: signal(status) } },
      ],
    });
    const fixture = TestBed.createComponent(OnboardingChecklistComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('renders the four steps from stubbed status', () => {
    const el = setup({
      mfa_enrolled: false, broker_connected: false, strategy_ready: false,
      first_fill_seen: false, complete: false,
    });
    expect(el.querySelectorAll('ol li').length).toBe(4);
  });

  it('shows a CTA for incomplete steps and hides it for complete ones', () => {
    const el = setup({
      mfa_enrolled: true, broker_connected: false, strategy_ready: false,
      first_fill_seen: false, complete: false,
    });
    const hrefs = Array.from(el.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('/settings/brokers');        // broker step incomplete → CTA
    expect(hrefs).not.toContain('/settings/security/mfa/setup'); // MFA done → no CTA
  });

  it('renders no steps before status loads', () => {
    const el = setup(null);
    expect(el.querySelectorAll('ol li').length).toBe(0);
  });
});
