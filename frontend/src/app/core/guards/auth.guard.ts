/** Redirects unauthenticated users to /login?next=<attempted-url>.
 *
 * P1-4: the refresh token now lives in an HttpOnly cookie the SPA can't read,
 * so authentication is judged solely by the in-memory auth state. On a cold
 * load the app-initializer's silent refresh (initSession) sets this before the
 * guard runs; a refresh-interceptor logout-on-401 clears it.
 */
import { inject } from '@angular/core';
import { CanMatchFn, Router, UrlSegment } from '@angular/router';
import { AuthStore } from '../../abstraction/stores/auth.store';

export const authGuard: CanMatchFn = (route, segments: UrlSegment[]) => {
  const store = inject(AuthStore);
  const router = inject(Router);

  if (store.isAuthenticated()) {
    return true;
  }

  const next = '/' + segments.map(s => s.path).join('/');
  return router.createUrlTree(['/login'], { queryParams: { next } });
};
