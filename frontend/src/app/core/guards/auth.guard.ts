/** Redirects unauthenticated users to /login?next=<attempted-url>. */
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
