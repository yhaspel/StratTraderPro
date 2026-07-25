/** Redirects authenticated users away from the public landing page ("/") to
 * /dashboard (M10.5 §7.1). Mirror of guestGuard, scoped to the landing route so
 * a signed-in user hitting "/" lands in the app, not on the marketing page. */
import { inject } from '@angular/core';
import { CanMatchFn, Router } from '@angular/router';
import { AuthStore } from '../../abstraction/stores/auth.store';

export const landingGuard: CanMatchFn = () => {
  const store = inject(AuthStore);
  const router = inject(Router);

  if (store.isAuthenticated()) {
    return router.createUrlTree(['/dashboard']);
  }
  return true;
};
