/** Redirects already-authenticated users away from auth pages. */
import { inject } from '@angular/core';
import { CanMatchFn, Router } from '@angular/router';
import { AuthStore } from '../../abstraction/stores/auth.store';

export const guestGuard: CanMatchFn = () => {
  const store = inject(AuthStore);
  const router = inject(Router);

  if (store.isAuthenticated()) {
    return router.createUrlTree(['/dashboard']);
  }
  return true;
};
