/** /risk child route (M08). Mounted under the shell parent, which enforces
 * authGuard once (M10.5 §7.1). MFA/permission enforcement is server-side. */
import { Routes } from '@angular/router';

export const RISK_ROUTES: Routes = [
  {
    path: 'risk',
    loadComponent: () => import('./risk.component').then(m => m.RiskComponent),
  },
];
