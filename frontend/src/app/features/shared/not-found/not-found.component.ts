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
      <p class="font-mono text-6xl font-semibold text-accent-700">404</p>
      <h1 class="mt-4 font-heading text-[32px] font-semibold leading-tight text-ink">
        {{ 'errors.not_found.title' | translate }}
      </h1>
      <p class="mt-2 text-neutral-700">{{ 'errors.not_found.body' | translate }}</p>
      <a
        [routerLink]="homeLink()"
        class="mt-6 inline-flex items-center justify-center rounded-none bg-accent-700 px-4 py-2 font-heading text-sm font-semibold text-bg transition-colors hover:bg-accent-800">
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
