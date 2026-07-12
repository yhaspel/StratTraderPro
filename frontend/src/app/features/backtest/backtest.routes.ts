/** /backtest/* child routes (M09). Mounted under the shell parent, which
 * enforces authGuard once (M10.5 §7.1). MFA/ownership enforcement is server-side. */
import { Routes } from '@angular/router';

export const BACKTEST_ROUTES: Routes = [
  {
    path: 'backtest',
    loadComponent: () =>
      import('./backtest-launcher.component').then(m => m.BacktestLauncherComponent),
  },
  {
    path: 'backtest/:id',
    loadComponent: () =>
      import('./backtest-detail.component').then(m => m.BacktestDetailComponent),
  },
];
