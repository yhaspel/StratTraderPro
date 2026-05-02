/** Redirects unauthenticated users to /login?next=<attempted-url>.
 *
 * Checks BOTH the in-memory auth state AND the persisted refresh token. If
 * the in-memory state thinks we're authed but the refresh token has been
 * cleared from storage (e.g. by the refresh-interceptor's logout-on-401),
 * we treat the user as unauthenticated and redirect. This prevents the
 * "stuck on /dashboard while logged out" UX where the SPA's stale signal
 * value lets navigation through after the persistence layer was wiped.
 */
import { inject } from '@angular/core';
import { CanMatchFn, Router, UrlSegment } from '@angular/router';
import { AuthStore } from '../../abstraction/stores/auth.store';

export const authGuard: CanMatchFn = (route, segments: UrlSegment[]) => {
  const store = inject(AuthStore);
  const router = inject(Router);

  if (store.isAuthenticated() && store.refreshToken()) {
    return true;
  }

  const next = '/' + segments.map(s => s.path).join('/');
  return router.createUrlTree(['/login'], { queryParams: { next } });
};
