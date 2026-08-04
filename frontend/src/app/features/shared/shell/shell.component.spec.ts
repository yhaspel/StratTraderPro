import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { ShellComponent } from './shell.component';
import { AuthStore } from '../../../abstraction/stores/auth.store';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { DashboardFacade } from '../../../abstraction/facades/dashboard.facade';
import { OnboardingFacade } from '../../../abstraction/facades/onboarding.facade';
import { RiskFacade } from '../../../abstraction/facades/risk.facade';
import { TermsFacade } from '../../../abstraction/facades/terms.facade';

describe('ShellComponent', () => {
  let authFacade: jasmine.SpyObj<AuthFacade>;
  let load: jasmine.Spy;
  let loadKillswitches: jasmine.Spy;
  let wsStart: jasmine.Spy;
  let wsStop: jasmine.Spy;

  function setup(
    user: { email: string; is_staff?: boolean } | null,
    incomplete = false,
    haltActive = false,
  ) {
    authFacade = jasmine.createSpyObj('AuthFacade', ['signOut']);
    authFacade.signOut.and.resolveTo();
    load = jasmine.createSpy('load');
    loadKillswitches = jasmine.createSpy('loadKillswitches');
    wsStart = jasmine.createSpy('start');
    wsStop = jasmine.createSpy('stop');
    TestBed.configureTestingModule({
      imports: [ShellComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthStore, useValue: { user: signal(user), isAuthenticated: signal(true) } },
        { provide: AuthFacade, useValue: authFacade },
        { provide: OnboardingFacade, useValue: { load, incomplete: signal(incomplete) } },
        { provide: RiskFacade, useValue: { haltActive: signal(haltActive), loadKillswitches } },
        {
          provide: DashboardFacade,
          useValue: { connected: signal(false), start: wsStart, stop: wsStop },
        },
        {
          provide: TermsFacade,
          useValue: {
            load: jasmine.createSpy('termsLoad'),
            needsAcceptance: signal(false),
            terms: signal(null),
            accepting: signal(false),
            error: signal(null),
            accept: jasmine.createSpy('accept'),
          },
        },
      ],
    });
    const fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => TestBed.resetTestingModule());

  function hrefs(el: HTMLElement): (string | null)[] {
    return Array.from(el.querySelectorAll('a')).map((a) => a.getAttribute('href'));
  }

  it('renders the primary nav links', () => {
    const el = setup({ email: 'a@b.c' }).nativeElement as HTMLElement;
    const links = hrefs(el);
    for (const link of ['/dashboard', '/strategies', '/backtest', '/risk', '/orders', '/guides', '/settings/profile']) {
      expect(links).toContain(link);
    }
  });

  it('hides the Admin link for non-staff', () => {
    const el = setup({ email: 'a@b.c', is_staff: false }).nativeElement as HTMLElement;
    expect(hrefs(el)).not.toContain('/admin');
  });

  it('shows the Admin link for staff', () => {
    const el = setup({ email: 'a@b.c', is_staff: true }).nativeElement as HTMLElement;
    expect(hrefs(el)).toContain('/admin');
  });

  it('loads onboarding status on init', () => {
    setup({ email: 'a@b.c' });
    expect(load).toHaveBeenCalled();
  });

  it('refreshes kill-switch state on init (halt banner lives in the shell)', () => {
    setup({ email: 'a@b.c' });
    expect(loadKillswitches).toHaveBeenCalled();
  });

  it('hides the halt banner when no kill switch is active', () => {
    const el = setup({ email: 'a@b.c' }).nativeElement as HTMLElement;
    expect(el.querySelector('[role="alert"].bg-down')).toBeNull();
  });

  it('shows the halt banner above the header when a kill switch is active', () => {
    const el = setup({ email: 'a@b.c' }, false, true).nativeElement as HTMLElement;
    const banner = el.querySelector('[role="alert"].bg-down');
    expect(banner).not.toBeNull();
    const header = el.querySelector('header');
    expect(header).not.toBeNull();
    // The banner must precede the header in document order.
    expect(
      banner!.compareDocumentPosition(header!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('opens the realtime stream on init so the Live dot is truthful on every route', () => {
    setup({ email: 'a@b.c' });
    expect(wsStart).toHaveBeenCalled();
  });

  it('releases its stream reference on destroy', () => {
    const fixture = setup({ email: 'a@b.c' });
    fixture.destroy();
    expect(wsStop).toHaveBeenCalled();
  });

  it('sign out delegates to AuthFacade.signOut', async () => {
    const fixture = setup({ email: 'a@b.c' });
    await fixture.componentInstance.signOut();
    expect(authFacade.signOut).toHaveBeenCalled();
  });
});
