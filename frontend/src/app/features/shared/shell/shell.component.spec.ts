import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { ShellComponent } from './shell.component';
import { AuthStore } from '../../../abstraction/stores/auth.store';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { OnboardingFacade } from '../../../abstraction/facades/onboarding.facade';

describe('ShellComponent', () => {
  let authFacade: jasmine.SpyObj<AuthFacade>;
  let load: jasmine.Spy;

  function setup(user: { email: string; is_staff?: boolean } | null, incomplete = false) {
    authFacade = jasmine.createSpyObj('AuthFacade', ['signOut']);
    authFacade.signOut.and.resolveTo();
    load = jasmine.createSpy('load');
    TestBed.configureTestingModule({
      imports: [ShellComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        { provide: AuthStore, useValue: { user: signal(user), isAuthenticated: signal(true) } },
        { provide: AuthFacade, useValue: authFacade },
        { provide: OnboardingFacade, useValue: { load, incomplete: signal(incomplete) } },
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
    for (const link of ['/dashboard', '/strategies', '/backtest', '/risk', '/orders', '/settings/profile']) {
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

  it('sign out delegates to AuthFacade.signOut', async () => {
    const fixture = setup({ email: 'a@b.c' });
    await fixture.componentInstance.signOut();
    expect(authFacade.signOut).toHaveBeenCalled();
  });
});
