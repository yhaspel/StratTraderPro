import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { landingGuard } from './core/guards/landing.guard';

import { SETTINGS_ROUTES } from './features/settings/settings.routes';
import { STRATEGIES_ROUTES } from './features/strategies/strategies.routes';
import { RISK_ROUTES } from './features/risk/risk.routes';
import { BACKTEST_ROUTES } from './features/backtest/backtest.routes';
import { ADMIN_ROUTES } from './features/admin/admin.routes';

/**
 * M10.5 §7.1 — one ShellComponent wraps every authenticated route via a
 * component-ful parent guarded once by authGuard; the public landing and auth
 * pages stay OUTSIDE the shell. A real 404 (`**`) replaces the old silent
 * `** → ''` redirect.
 */
export const routes: Routes = [
  // Public landing — redirect authed users to /dashboard (landingGuard).
  {
    path: '',
    pathMatch: 'full',
    canMatch: [landingGuard],
    loadComponent: () =>
      import('./features/landing/landing.component').then(m => m.LandingComponent),
  },

  // Auth pages — NO shell (login/register/mfa/oauth/…).
  {
    path: '',
    loadChildren: () => import('./features/auth/auth.routes').then(m => m.AUTH_ROUTES),
  },

  // Authenticated app — ONE shell wrapping everything, guarded once.
  {
    path: '',
    canMatch: [authGuard],
    loadComponent: () =>
      import('./features/shared/shell/shell.component').then(m => m.ShellComponent),
    children: [
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
      },
      {
        path: 'orders',
        loadComponent: () =>
          import('./features/orders/orders.component').then(m => m.OrdersComponent),
      },
      ...SETTINGS_ROUTES,
      ...STRATEGIES_ROUTES,
      ...RISK_ROUTES,
      ...BACKTEST_ROUTES,
      ...ADMIN_ROUTES,
      {
        path: 'help/:slug',
        loadComponent: () =>
          import('./features/help/help-article.component').then(m => m.HelpArticleComponent),
      },
    ],
  },

  // Real 404 (replaces the silent `** -> ''`).
  {
    path: '**',
    loadComponent: () =>
      import('./features/shared/not-found/not-found.component').then(m => m.NotFoundComponent),
  },
];
