import { Routes } from '@angular/router';
import { authGuard } from '../../core/guards/auth.guard';

export const SETTINGS_ROUTES: Routes = [
  {
    path: 'settings/profile',
    canMatch: [authGuard],
    loadComponent: () => import('./profile/profile.component').then(m => m.ProfileComponent),
  },
  {
    path: 'settings/security',
    canMatch: [authGuard],
    loadComponent: () => import('./security/security.component').then(m => m.SecurityComponent),
  },
  {
    path: 'settings/security/mfa/setup',
    canMatch: [authGuard],
    loadComponent: () => import('./mfa-setup/mfa-setup.component').then(m => m.MfaSetupComponent),
  },
];
