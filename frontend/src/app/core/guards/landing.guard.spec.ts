import { TestBed } from '@angular/core/testing';
import { UrlTree, provideRouter } from '@angular/router';
import { landingGuard } from './landing.guard';
import { AuthStore } from '../../abstraction/stores/auth.store';

describe('landingGuard', () => {
  function run(authed: boolean): boolean | UrlTree {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: AuthStore, useValue: { isAuthenticated: () => authed } },
      ],
    });
    return TestBed.runInInjectionContext(() => landingGuard({} as never, [] as never)) as boolean | UrlTree;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('allows anonymous users to see the landing', () => {
    expect(run(false)).toBeTrue();
  });

  it('redirects authenticated users to /dashboard', () => {
    const result = run(true);
    expect(result instanceof UrlTree).toBeTrue();
    expect((result as UrlTree).toString()).toBe('/dashboard');
  });
});
