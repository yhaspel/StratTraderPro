/** /strategies/* child routes (M03). Mounted under the shell parent, which
 * enforces authGuard once (M10.5 §7.1). MFA enforcement is server-side. */
import { Routes } from '@angular/router';

export const STRATEGIES_ROUTES: Routes = [
  {
    path: 'strategies',
    loadComponent: () =>
      import('./list/strategies-list.component').then(m => m.StrategiesListComponent),
  },
  {
    path: 'strategies/upload',
    loadComponent: () =>
      import('./upload/strategies-upload.component').then(m => m.StrategiesUploadComponent),
  },
  {
    path: 'strategies/:id',
    loadComponent: () =>
      import('./detail/strategies-detail.component').then(m => m.StrategiesDetailComponent),
  },
];
