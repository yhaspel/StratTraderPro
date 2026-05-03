/** /strategies/* — lazy-loaded route group (M03). MFA enforcement happens
 * server-side; the client guard here is just `authGuard` so routing matches
 * the rest of the app pattern.
 */
import { Routes } from '@angular/router';
import { authGuard } from '../../core/guards/auth.guard';

export const STRATEGIES_ROUTES: Routes = [
  {
    path: 'strategies',
    canMatch: [authGuard],
    loadComponent: () =>
      import('./list/strategies-list.component').then(m => m.StrategiesListComponent),
  },
  {
    path: 'strategies/upload',
    canMatch: [authGuard],
    loadComponent: () =>
      import('./upload/strategies-upload.component').then(m => m.StrategiesUploadComponent),
  },
  {
    path: 'strategies/:id',
    canMatch: [authGuard],
    loadComponent: () =>
      import('./detail/strategies-detail.component').then(m => m.StrategiesDetailComponent),
  },
];
