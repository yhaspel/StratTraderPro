/** /admin/* — lazy-loaded route group (M10 Admin Portal).
 *
 * Every route runs `authGuard` (must be signed in) then `adminGuard` (must be
 * staff). The backend independently enforces staff + MFA on the API; these
 * guards are a client-side UX gate. The whole group is a lazy chunk so it never
 * lands in the initial bundle.
 */
import { Routes } from '@angular/router';
import { authGuard } from '../../core/guards/auth.guard';
import { adminGuard } from '../../core/guards/admin.guard';

export const ADMIN_ROUTES: Routes = [
  {
    path: 'admin',
    canMatch: [authGuard, adminGuard],
    loadComponent: () =>
      import('./admin-overview.component').then(m => m.AdminOverviewComponent),
  },
  {
    path: 'admin/users',
    canMatch: [authGuard, adminGuard],
    loadComponent: () =>
      import('./admin-users.component').then(m => m.AdminUsersComponent),
  },
  {
    path: 'admin/users/:id',
    canMatch: [authGuard, adminGuard],
    loadComponent: () =>
      import('./admin-user-detail.component').then(m => m.AdminUserDetailComponent),
  },
  {
    path: 'admin/audit',
    canMatch: [authGuard, adminGuard],
    loadComponent: () =>
      import('./admin-audit.component').then(m => m.AdminAuditComponent),
  },
  {
    path: 'admin/flags',
    canMatch: [authGuard, adminGuard],
    loadComponent: () =>
      import('./admin-flags.component').then(m => m.AdminFlagsComponent),
  },
  {
    path: 'admin/health',
    canMatch: [authGuard, adminGuard],
    loadComponent: () =>
      import('./admin-health.component').then(m => m.AdminHealthComponent),
  },
];
