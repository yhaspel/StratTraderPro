/** /backtest/* — lazy-loaded route group (M09). MFA/ownership enforcement is
 * server-side; the client guard is `authGuard` to match the rest of the app.
 */
import { Routes } from '@angular/router';
import { authGuard } from '../../core/guards/auth.guard';

export const BACKTEST_ROUTES: Routes = [
  {
    path: 'backtest',
    canMatch: [authGuard],
    loadComponent: () =>
      import('./backtest-launcher.component').then(m => m.BacktestLauncherComponent),
  },
  {
    path: 'backtest/:id',
    canMatch: [authGuard],
    loadComponent: () =>
      import('./backtest-detail.component').then(m => m.BacktestDetailComponent),
  },
];
