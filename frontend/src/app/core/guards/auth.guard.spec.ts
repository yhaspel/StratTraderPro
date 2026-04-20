import { TestBed } from '@angular/core/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';
import { UrlSegment } from '@angular/router';
import { authGuard } from './auth.guard';
import { AuthStore } from '../../abstraction/stores/auth.store';
import { AuthUser } from '../../core/models/auth.models';

const mockUser: AuthUser = {
  id: 'u1', email: 'a@b.com', display_name: 'A', is_verified: true,
};

function runGuard(segments: string[]): boolean | UrlTree {
  return TestBed.runInInjectionContext(() =>
    authGuard(
      {} as any,
      segments.map(p => ({ path: p } as UrlSegment)),
    ) as boolean | UrlTree
  );
}

describe('authGuard', () => {
  let store: AuthStore;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    store = TestBed.inject(AuthStore);
    router = TestBed.inject(Router);
  });

  afterEach(() => localStorage.clear());

  it('returns true when user is authenticated', () => {
    store.setAuthed(mockUser, 'access', 'refresh');
    expect(runGuard(['dashboard'])).toBeTrue();
  });

  it('redirects to /login when not authenticated', () => {
    const result = runGuard(['dashboard']) as UrlTree;
    expect(result).toBeInstanceOf(UrlTree);
    expect(router.serializeUrl(result)).toBe('/login?next=%2Fdashboard');
  });

  it('preserves full nested path in ?next query param', () => {
    const result = runGuard(['strategies', 'new']) as UrlTree;
    expect(result).toBeInstanceOf(UrlTree);
    expect(router.serializeUrl(result)).toBe('/login?next=%2Fstrategies%2Fnew');
  });

  it('returns false-ish (UrlTree) when status is loading, not authed', () => {
    store.setLoading();
    const result = runGuard(['dashboard']);
    expect(result).toBeInstanceOf(UrlTree);
  });
});
