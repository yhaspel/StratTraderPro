/** /settings/* child routes (M02). Mounted under the shell parent, which
 * enforces authGuard once (M10.5 §7.1) — so no per-route canMatch here. */
import { Routes } from '@angular/router';

export const SETTINGS_ROUTES: Routes = [
  {
    path: 'settings/profile',
    loadComponent: () => import('./profile/profile.component').then(m => m.ProfileComponent),
  },
  {
    path: 'settings/security',
    loadComponent: () => import('./security/security.component').then(m => m.SecurityComponent),
  },
  {
    path: 'settings/security/mfa/setup',
    loadComponent: () => import('./mfa-setup/mfa-setup.component').then(m => m.MfaSetupComponent),
  },
  {
    path: 'settings/brokers',
    loadComponent: () => import('./brokers/brokers.component').then(m => m.BrokersComponent),
  },
  {
    path: 'settings/data-providers',
    loadComponent: () =>
      import('./data-providers/data-providers.component').then(m => m.DataProvidersComponent),
  },
];
