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
      import('./features/landing/landing.component').then(m => m.LandingComponent),
    // TODO(M03+): replace with real dashboard component
  },
  { path: '**', redirectTo: '' },
];
