/** /admin/* child routes (M10 Admin Portal). Mounted under the shell parent,
 * which enforces authGuard once (M10.5 §7.1); each route additionally keeps
 * `adminGuard` (the staff gate is separate from the auth gate). Backend
 * independently enforces staff + MFA. */
import { Routes } from '@angular/router';
import { adminGuard } from '../../core/guards/admin.guard';

export const ADMIN_ROUTES: Routes = [
  {
    path: 'admin',
    canMatch: [adminGuard],
    loadComponent: () =>
      import('./admin-overview.component').then(m => m.AdminOverviewComponent),
  },
  {
    path: 'admin/users',
    canMatch: [adminGuard],
    loadComponent: () =>
      import('./admin-users.component').then(m => m.AdminUsersComponent),
  },
  {
    path: 'admin/users/:id',
    canMatch: [adminGuard],
    loadComponent: () =>
      import('./admin-user-detail.component').then(m => m.AdminUserDetailComponent),
  },
  {
    path: 'admin/audit',
    canMatch: [adminGuard],
    loadComponent: () =>
      import('./admin-audit.component').then(m => m.AdminAuditComponent),
  },
  {
    path: 'admin/flags',
    canMatch: [adminGuard],
    loadComponent: () =>
      import('./admin-flags.component').then(m => m.AdminFlagsComponent),
  },
  {
    path: 'admin/health',
    canMatch: [adminGuard],
    loadComponent: () =>
      import('./admin-health.component').then(m => m.AdminHealthComponent),
  },
];
