import { TestBed } from '@angular/core/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';
import { adminGuard } from './admin.guard';
import { AuthStore } from '../../abstraction/stores/auth.store';
import { AuthUser } from '../../core/models/auth.models';

const staffUser: AuthUser = {
  id: 'u1', email: 'admin@b.com', display_name: 'Admin', is_verified: true, is_staff: true,
};
const plainUser: AuthUser = {
  id: 'u2', email: 'trader@b.com', display_name: 'Trader', is_verified: true, is_staff: false,
};

function runGuard(): boolean | UrlTree {
  return TestBed.runInInjectionContext(
    () => adminGuard({} as any, []) as boolean | UrlTree,
  );
}

describe('adminGuard', () => {
  let store: AuthStore;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    store = TestBed.inject(AuthStore);
    router = TestBed.inject(Router);
  });

  afterEach(() => localStorage.clear());

  it('returns true when the user is staff', () => {
    store.setAuthed(staffUser, 'access');
    expect(runGuard()).toBeTrue();
  });

  it('redirects to /dashboard when the user is not staff', () => {
    store.setAuthed(plainUser, 'access');
    const result = runGuard() as UrlTree;
    expect(result).toBeInstanceOf(UrlTree);
    expect(router.serializeUrl(result)).toBe('/dashboard');
  });

  it('redirects to /dashboard when there is no user', () => {
    const result = runGuard() as UrlTree;
    expect(result).toBeInstanceOf(UrlTree);
    expect(router.serializeUrl(result)).toBe('/dashboard');
  });
});
