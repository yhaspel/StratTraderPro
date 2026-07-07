/** /risk — lazy-loaded route group (M08). Client guard is `authGuard`;
 * MFA/permission enforcement happens server-side. */
import { Routes } from '@angular/router';
import { authGuard } from '../../core/guards/auth.guard';

export const RISK_ROUTES: Routes = [
  {
    path: 'risk',
    canMatch: [authGuard],
    loadComponent: () => import('./risk.component').then(m => m.RiskComponent),
  },
];
