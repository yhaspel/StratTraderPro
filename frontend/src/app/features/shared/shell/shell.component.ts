/** Application shell (M10.5 §7.1) — wraps every authenticated route.
 *
 * Responsive header (role="banner") with the product wordmark, role-aware
 * primary nav, and a user menu exposing Sign out; a skip-to-content link; the
 * impersonation banner slot; the global toast host; and <router-outlet> inside
 * <main id="main-content">. Reads the user from AuthStore (F-11, no new store)
 * and getting-started state from OnboardingFacade. Sign out routes through
 * AuthFacade.signOut() which also tears down the shared dashboard WebSocket.
 */
import {
  ChangeDetectionStrategy, Component, HostListener, OnInit, inject, signal,
} from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

import { AuthStore } from '../../../abstraction/stores/auth.store';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { OnboardingFacade } from '../../../abstraction/facades/onboarding.facade';
import { ImpersonationBannerComponent } from '../../admin/impersonation-banner.component';
import { ToastHostComponent } from '../ui/toast/toast-host.component';

interface NavItem {
  key: string;
  link: string;
}

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    RouterLink, RouterLinkActive, RouterOutlet, TranslateModule,
    ImpersonationBannerComponent, ToastHostComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      href="#main-content"
      class="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[70] focus:rounded-md focus:bg-primary-600 focus:px-3 focus:py-2 focus:text-white">
      {{ 'nav.skip_to_content' | translate }}
    </a>

    <app-toast-host />
    <app-impersonation-banner />

    <header role="banner" class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-7xl items-center justify-between gap-md px-4 py-3">
        <a routerLink="/dashboard" class="text-lg font-bold text-primary-900">
          {{ 'app.title' | translate }}
        </a>

        <!-- Desktop nav -->
        <nav [attr.aria-label]="'nav.primary' | translate" class="hidden items-center gap-1 md:flex">
          @for (item of navItems(); track item.link) {
            <a
              [routerLink]="item.link"
              routerLinkActive="bg-primary-50 text-primary-700"
              class="rounded-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100">
              {{ item.key | translate }}
            </a>
          }
          @if (onboarding.incomplete()) {
            <a
              routerLink="/dashboard"
              class="rounded-md bg-accent-500/10 px-3 py-2 text-sm font-medium text-accent-500 hover:bg-accent-500/20">
              {{ 'nav.getting_started' | translate }}
            </a>
          }
        </nav>

        <div class="flex items-center gap-sm">
          <!-- User menu -->
          <div class="relative">
            <button
              type="button"
              class="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
              aria-haspopup="menu"
              [attr.aria-expanded]="menuOpen()"
              (click)="toggleMenu($event)">
              <span class="hidden sm:inline">{{ userLabel() }}</span>
              <span aria-hidden="true">▾</span>
            </button>
            @if (menuOpen()) {
              <div
                role="menu"
                class="absolute right-0 z-[65] mt-1 w-48 rounded-md border border-slate-200 bg-white py-1 shadow-md">
                <a
                  role="menuitem"
                  routerLink="/settings/profile"
                  class="block px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
                  (click)="closeMenu()">
                  {{ 'nav.settings' | translate }}
                </a>
                <a
                  role="menuitem"
                  routerLink="/help"
                  class="block px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
                  (click)="closeMenu()">
                  {{ 'nav.help' | translate }}
                </a>
                <button
                  type="button"
                  role="menuitem"
                  class="block w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
                  (click)="signOut()">
                  {{ 'nav.logout' | translate }}
                </button>
              </div>
            }
          </div>

          <!-- Mobile hamburger -->
          <button
            type="button"
            class="rounded-md p-2 text-slate-600 hover:bg-slate-100 md:hidden focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
            [attr.aria-label]="'nav.open_menu' | translate"
            [attr.aria-expanded]="drawerOpen()"
            (click)="toggleDrawer($event)">
            <span aria-hidden="true">☰</span>
          </button>
        </div>
      </div>

      <!-- Mobile drawer -->
      @if (drawerOpen()) {
        <nav [attr.aria-label]="'nav.primary' | translate" class="border-t border-slate-200 px-4 py-2 md:hidden">
          @for (item of navItems(); track item.link) {
            <a
              [routerLink]="item.link"
              routerLinkActive="bg-primary-50 text-primary-700"
              class="block rounded-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
              (click)="closeDrawer()">
              {{ item.key | translate }}
            </a>
          }
          @if (onboarding.incomplete()) {
            <a
              routerLink="/dashboard"
              class="block rounded-md px-3 py-2 text-sm font-medium text-accent-500 hover:bg-slate-100"
              (click)="closeDrawer()">
              {{ 'nav.getting_started' | translate }}
            </a>
          }
        </nav>
      }
    </header>

    <main id="main-content" class="mx-auto max-w-7xl px-4 py-6">
      <router-outlet />
    </main>
  `,
})
export class ShellComponent implements OnInit {
  private store = inject(AuthStore);
  private auth = inject(AuthFacade);
  readonly onboarding = inject(OnboardingFacade);

  readonly menuOpen = signal(false);
  readonly drawerOpen = signal(false);

  private readonly baseNav: NavItem[] = [
    { key: 'nav.dashboard', link: '/dashboard' },
    { key: 'nav.strategies', link: '/strategies' },
    { key: 'nav.backtest', link: '/backtest' },
    { key: 'nav.risk', link: '/risk' },
    { key: 'nav.orders', link: '/orders' },
    { key: 'nav.settings', link: '/settings/profile' },
  ];

  ngOnInit(): void {
    void this.onboarding.load();
  }

  navItems(): NavItem[] {
    return this.store.user()?.is_staff
      ? [...this.baseNav, { key: 'nav.admin', link: '/admin' }]
      : this.baseNav;
  }

  userLabel(): string {
    const u = this.store.user();
    return u?.display_name || u?.email || '';
  }

  toggleMenu(ev: MouseEvent): void {
    ev.stopPropagation();
    this.menuOpen.update((v) => !v);
  }

  closeMenu(): void {
    this.menuOpen.set(false);
  }

  toggleDrawer(ev: MouseEvent): void {
    ev.stopPropagation();
    this.drawerOpen.update((v) => !v);
  }

  closeDrawer(): void {
    this.drawerOpen.set(false);
  }

  async signOut(): Promise<void> {
    this.closeMenu();
    await this.auth.signOut();
  }

  @HostListener('document:click')
  onDocumentClick(): void {
    this.closeMenu();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.closeMenu();
    this.closeDrawer();
  }
}
