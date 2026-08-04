/** TermsGateComponent — blocking modal shows on needs_acceptance, hides after
 * accept (M11 §7.8). */
import { WritableSignal, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslateModule } from '@ngx-translate/core';

import { TermsGateComponent } from './terms-gate.component';
import { TermsFacade } from '../../../abstraction/facades/terms.facade';
import { TermsCurrent } from '../../../core/models/terms.models';

const SAMPLE: TermsCurrent = {
  tos_version: '2026-07-01',
  tos_url: 'https://example.test/tos',
  privacy_version: '2026-07-01',
  privacy_url: 'https://example.test/privacy',
  needs_acceptance: true,
};

describe('TermsGateComponent', () => {
  let fixture: ComponentFixture<TermsGateComponent>;
  let needsAcceptance: WritableSignal<boolean>;
  let accept: jasmine.Spy;

  function setup(needs: boolean) {
    needsAcceptance = signal(needs);
    accept = jasmine.createSpy('accept').and.callFake(async () => {
      needsAcceptance.set(false); // real facade clears the gate on success
      return true;
    });
    TestBed.configureTestingModule({
      imports: [TermsGateComponent, TranslateModule.forRoot()],
      providers: [
        {
          provide: TermsFacade,
          useValue: {
            needsAcceptance,
            terms: signal(SAMPLE),
            accepting: signal(false),
            error: signal(null),
            accept,
          },
        },
      ],
    });
    fixture = TestBed.createComponent(TermsGateComponent);
    fixture.detectChanges();
  }

  afterEach(() => TestBed.resetTestingModule());

  function dialog(): HTMLElement | null {
    return fixture.nativeElement.querySelector('[role="dialog"]');
  }

  it('does NOT render the modal when acceptance is not needed', () => {
    setup(false);
    expect(dialog()).toBeNull();
  });

  it('renders a blocking modal (no ✕) with both version links when acceptance is needed', () => {
    setup(true);
    expect(dialog()).toBeTruthy();
    // Blocking: the shared modal hides its ✕ close affordance when dismissable=false.
    expect(fixture.nativeElement.querySelector('[aria-label]')).toBeNull();
    const hrefs = Array.from(fixture.nativeElement.querySelectorAll('a')).map((a) =>
      (a as HTMLAnchorElement).getAttribute('href'),
    );
    expect(hrefs).toContain(SAMPLE.tos_url);
    expect(hrefs).toContain(SAMPLE.privacy_url);
  });

  it('accept action calls the facade and hides the modal on success', async () => {
    setup(true);
    const button = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    button.click();
    await fixture.whenStable();
    expect(accept).toHaveBeenCalled();
    fixture.detectChanges();
    expect(dialog()).toBeNull();
  });
});
