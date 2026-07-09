/** Gates the /admin feature area to staff users.
 *
 * Runs alongside `authGuard` on every admin route. Reads the current user from
 * the same AuthStore the rest of the app uses; when the user is missing or not
 * staff, redirects to /dashboard. The backend remains authoritative (staff +
 * MFA are enforced server-side) — this guard is a client-side UX gate only.
 */
import { inject } from '@angular/core';
import { CanMatchFn, Router } from '@angular/router';
import { AuthStore } from '../../abstraction/stores/auth.store';

export const adminGuard: CanMatchFn = () => {
  const store = inject(AuthStore);
  const router = inject(Router);

  if (store.user()?.is_staff) {
    return true;
  }
  return router.createUrlTree(['/dashboard']);
};
