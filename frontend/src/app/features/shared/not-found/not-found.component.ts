/** Real 404 page (M10.5 §7.1/AC-10.5-4) — replaces the old silent `** → ''`
 * redirect that dumped users on the landing scaffold. Rendered OUTSIDE the
 * shell (it is the top-level `**` route). Links home: /dashboard when authed,
 * otherwise the public landing. */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthStore } from '../../../abstraction/stores/auth.store';

@Component({
  selector: 'app-not-found',
  standalone: true,
  imports: [RouterLink, TranslateModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="mx-auto max-w-lg px-4 py-24 text-center">
      <p class="text-6xl font-bold text-primary-900">404</p>
      <h1 class="mt-4 text-2xl font-semibold text-slate-800">
        {{ 'errors.not_found.title' | translate }}
      </h1>
      <p class="mt-2 text-slate-600">{{ 'errors.not_found.body' | translate }}</p>
      <a
        [routerLink]="homeLink()"
        class="mt-6 inline-flex rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700">
        {{ 'errors.not_found.home' | translate }}
      </a>
    </main>
  `,
})
export class NotFoundComponent {
  private store = inject(AuthStore);

  homeLink(): string {
    return this.store.isAuthenticated() ? '/dashboard' : '/';
  }
}
