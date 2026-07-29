/** /guides/* routes (M12 §7.1). Mounted under the shell parent, which enforces
 *  authGuard once (M10.5 §7.1).
 *
 *  The legacy /help and /help/:slug paths redirect here: they were shipped in
 *  M10.5, are linked from every inline "?" affordance in older builds, and may
 *  be bookmarked — a silent 404 on those would be a regression, not a rename.
 */
import { Routes } from '@angular/router';

export const GUIDES_ROUTES: Routes = [
  {
    path: 'guides',
    pathMatch: 'full',
    loadComponent: () =>
      import('./guides-index.component').then(m => m.GuidesIndexComponent),
  },
  {
    path: 'guides/:slug',
    loadComponent: () =>
      import('./guides-article.component').then(m => m.GuidesArticleComponent),
  },
  { path: 'help', pathMatch: 'full', redirectTo: 'guides' },
  { path: 'help/:slug', redirectTo: 'guides/:slug' },
];
