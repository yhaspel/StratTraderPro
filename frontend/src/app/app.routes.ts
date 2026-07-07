import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./features/landing/landing.component').then(
        (m) => m.LandingComponent
      ),
  },
  // Auth pages (lazy-loaded, flat routes)
  {
    path: '',
    loadChildren: () =>
      import('./features/auth/auth.routes').then(m => m.AUTH_ROUTES),
  },
  // Settings (M02): /settings/profile, /settings/security, /settings/security/mfa/setup
  {
    path: '',
    loadChildren: () =>
      import('./features/settings/settings.routes').then(m => m.SETTINGS_ROUTES),
  },
  // Strategies (M03): /strategies, /strategies/upload, /strategies/:id
  {
    path: '',
    loadChildren: () =>
      import('./features/strategies/strategies.routes').then(m => m.STRATEGIES_ROUTES),
  },
  // Protected routes
  {
    path: 'dashboard',
    canMatch: [authGuard],
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
  },
  // Orders (M05): /orders — lifecycle browser + reconciliation events
  {
    path: 'orders',
    canMatch: [authGuard],
    loadComponent: () =>
      import('./features/orders/orders.component').then(m => m.OrdersComponent),
  },
  // Risk (M08): /risk — profile editor, kill switches, and audit feeds
  {
    path: '',
    loadChildren: () =>
      import('./features/risk/risk.routes').then(m => m.RISK_ROUTES),
  },
  { path: '**', redirectTo: '' },
];
