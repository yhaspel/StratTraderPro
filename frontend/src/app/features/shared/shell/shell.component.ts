/** Application shell (M10.5 §7.1, "Industry" restyle) — wraps every
 * authenticated route.
 *
 * Light 54px header on the ground (bg-bg) with a bottom hairline: framed
 * bar-chart logomark + Barlow Condensed wordmark ("Pro" in accent), role-aware
 * primary nav (active = accent text + 2px accent underline), Live dot and a
 * user menu exposing Sign out; a skip-to-content link; the platform/user halt
 * banner ABOVE the header (solid --down, condensed uppercase — moved here from
 * the dashboard so it shows on every route); the impersonation banner slot;
 * the global toast host; and <router-outlet> inside <main id="main-content">.
 * Reads the user from AuthStore (F-11, no new store), getting-started state
 * from OnboardingFacade, halt state from RiskFacade (same signal the dashboard
 * used) and stream state from DashboardFacade. Sign out routes through
 * AuthFacade.signOut() which also tears down the shared dashboard WebSocket.
 */
import {
  ChangeDetectionStrategy, Component, ElementRef, HostListener, OnDestroy, OnInit, ViewChild,
  inject, signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { TranslateModule } from '@ngx-translate/core';

import { AuthStore } from '../../../abstraction/stores/auth.store';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { DashboardFacade } from '../../../abstraction/facades/dashboard.facade';
import { OnboardingFacade } from '../../../abstraction/facades/onboarding.facade';
import { RiskFacade } from '../../../abstraction/facades/risk.facade';
import { TermsFacade } from '../../../abstraction/facades/terms.facade';
import { ImpersonationBannerComponent } from '../../admin/impersonation-banner.component';
import { ToastHostComponent } from '../ui/toast/toast-host.component';
import { TermsGateComponent } from '../terms/terms-gate.component';

interface NavItem {
  key: string;
  link: string;
}

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    RouterLink, RouterLinkActive, RouterOutlet, TranslateModule,
    ImpersonationBannerComponent, ToastHostComponent, TermsGateComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      href="#main-content"
      class="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[70] focus:rounded-none focus:bg-accent-700 focus:px-3 focus:py-2 focus:text-bg">
      {{ 'nav.skip_to_content' | translate }}
    </a>

    <app-toast-host />
    <app-terms-gate />

    <!-- Platform/user halt banner — above the header, on every route. -->
    @if (risk.haltActive()) {
      <div
        role="alert"
        class="bg-down px-6 py-[9px] text-center font-heading text-sm font-semibold uppercase tracking-[.03em] text-bg">
        {{ 'risk.halt_banner' | translate }}
      </div>
    }

    <app-impersonation-banner />

    <header role="banner" class="border-b border-divider bg-bg">
      <div class="mx-auto flex h-[54px] max-w-7xl items-center justify-between gap-4 px-6">
        <div class="flex items-center gap-6">
          <!-- Framed bar-chart logomark + wordmark -->
          <a
            routerLink="/dashboard"
            class="flex items-center gap-[9px]"
            [attr.aria-label]="'app.title' | translate">
            <span
              aria-hidden="true"
              class="inline-flex h-6 w-6 items-end justify-center gap-[2px] border border-ink px-1 pb-[3px] pt-1">
              <span class="h-[7px] w-[3px] bg-accent"></span>
              <span class="h-[11px] w-[3px] bg-accent"></span>
              <span class="h-[5px] w-[3px] bg-accent-400"></span>
            </span>
            <span aria-hidden="true" class="whitespace-nowrap font-heading text-[18px] font-semibold text-ink">StratTrader<span class="text-accent-700">Pro</span></span>
          </a>

          <!-- Desktop nav -->
          <nav [attr.aria-label]="'nav.primary' | translate" class="hidden items-center gap-[18px] md:flex">
            @for (item of navItems(); track item.link) {
              <a
                [routerLink]="item.link"
                routerLinkActive="border-accent text-accent-700 font-medium"
                ariaCurrentWhenActive="page"
                class="border-b-2 border-transparent pb-[14px] pt-4 text-sm text-neutral-700 hover:text-accent-700">
                {{ item.key | translate }}
              </a>
            }
            @if (onboarding.incomplete()) {
              <a
                routerLink="/dashboard"
                class="border-b-2 border-transparent pb-[14px] pt-4 text-sm font-medium text-accent-700 hover:bg-accent-100">
                {{ 'nav.getting_started' | translate }}
              </a>
            }
          </nav>
        </div>

        <div class="flex items-center gap-[14px]">
          <!-- Live dot (square, up-green — stream state, never color-only).
               The label is ambiguous on its own ("is the APP offline?"), so the
               title says which thing is offline and what it costs you. -->
          <span class="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-neutral-700"
                [title]="(dashboard.connected() ? 'dashboard.live_hint' : 'dashboard.offline_hint') | translate">
            <span
              class="h-[7px] w-[7px] flex-none"
              [class.bg-up]="dashboard.connected()"
              [class.bg-neutral-400]="!dashboard.connected()"
              aria-hidden="true"></span>
            {{ (dashboard.connected() ? 'dashboard.live' : 'dashboard.offline') | translate }}
          </span>

          <!-- User menu -->
          <div class="relative">
            <button
              type="button"
              class="flex items-center gap-2 rounded-none px-3 py-2 text-[13px] font-medium text-ink hover:bg-neutral-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              aria-haspopup="menu"
              [attr.aria-expanded]="menuOpen()"
              (click)="toggleMenu($event)">
              <span class="hidden sm:inline">{{ userLabel() }}</span>
              <span aria-hidden="true" class="text-neutral-700">▾</span>
            </button>
            @if (menuOpen()) {
              <div
                role="menu"
                class="absolute right-0 z-[65] mt-1 w-48 rounded-none border border-divider bg-bg py-1 shadow-md">
                <a
                  role="menuitem"
                  routerLink="/settings/profile"
                  class="block px-4 py-2 text-sm text-ink hover:bg-neutral-200"
                  (click)="closeMenu()">
                  {{ 'nav.settings' | translate }}
                </a>
                <a
                  role="menuitem"
                  routerLink="/guides"
                  class="block px-4 py-2 text-sm text-ink hover:bg-neutral-200"
                  (click)="closeMenu()">
                  {{ 'nav.guides' | translate }}
                </a>
                <button
                  type="button"
                  role="menuitem"
                  class="block w-full px-4 py-2 text-left text-sm text-ink hover:bg-neutral-200"
                  (click)="signOut()">
                  {{ 'nav.logout' | translate }}
                </button>
              </div>
            }
          </div>

          <!-- Mobile hamburger -->
          <button
            type="button"
            class="rounded-none p-2 text-neutral-700 hover:bg-neutral-200 md:hidden focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            [attr.aria-label]="'nav.open_menu' | translate"
            [attr.aria-expanded]="drawerOpen()"
            (click)="toggleDrawer($event)">
            <span aria-hidden="true">☰</span>
          </button>
        </div>
      </div>

      <!-- Mobile drawer -->
      @if (drawerOpen()) {
        <nav [attr.aria-label]="'nav.primary' | translate" class="border-t border-divider px-4 py-2 md:hidden">
          @for (item of navItems(); track item.link) {
            <a
              [routerLink]="item.link"
              routerLinkActive="text-accent-700 font-medium"
              ariaCurrentWhenActive="page"
              class="block rounded-none px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-200"
              (click)="closeDrawer()">
              {{ item.key | translate }}
            </a>
          }
          @if (onboarding.incomplete()) {
            <a
              routerLink="/dashboard"
              class="block rounded-none px-3 py-2 text-sm font-medium text-accent-700 hover:bg-neutral-200"
              (click)="closeDrawer()">
              {{ 'nav.getting_started' | translate }}
            </a>
          }
        </nav>
      }
    </header>

    <!-- P2-DESIGN-3: SR announcement of the page change (focus moves to <main>). -->
    <p class="sr-only" aria-live="polite" role="status">{{ routeAnnouncement() }}</p>

    <main #main id="main-content" tabindex="-1" class="mx-auto w-full max-w-7xl px-6 pb-20 pt-7 focus:outline-none">
      <router-outlet />
    </main>
  `,
})
export class ShellComponent implements OnInit, OnDestroy {
  private store = inject(AuthStore);
  private auth = inject(AuthFacade);
  readonly onboarding = inject(OnboardingFacade);
  readonly risk = inject(RiskFacade);
  readonly dashboard = inject(DashboardFacade);
  private terms = inject(TermsFacade);
  private router = inject(Router);

  @ViewChild('main') private main?: ElementRef<HTMLElement>;
  readonly menuOpen = signal(false);
  readonly drawerOpen = signal(false);
  /** P2-DESIGN-3 — polite SR announcement of the newly-focused page. */
  readonly routeAnnouncement = signal('');

  constructor() {
    // On each completed navigation move focus to <main> and announce the page,
    // so keyboard/SR users aren't stranded on the clicked nav link.
    this.router.events
      .pipe(filter((e) => e instanceof NavigationEnd), takeUntilDestroyed())
      .subscribe(() => this.onNavigated());
  }

  private onNavigated(): void {
    // Defer so the new view (its <h1>) has rendered.
    setTimeout(() => {
      const el = this.main?.nativeElement;
      if (!el) { return; }
      el.focus();
      const heading = el.querySelector('h1')?.textContent?.trim();
      this.routeAnnouncement.set(heading ? `${heading} — page loaded` : 'Page loaded');
    });
  }

  private readonly baseNav: NavItem[] = [
    { key: 'nav.dashboard', link: '/dashboard' },
    { key: 'nav.strategies', link: '/strategies' },
    { key: 'nav.backtest', link: '/backtest' },
    { key: 'nav.risk', link: '/risk' },
    { key: 'nav.orders', link: '/orders' },
    { key: 'nav.guides', link: '/guides' },
    { key: 'nav.settings', link: '/settings/profile' },
  ];

  ngOnInit(): void {
    void this.onboarding.load();
    void this.terms.load(); // M11 §7.8 — blocking terms re-acceptance gate
    // Halt banner lives in the shell now — refresh the active kill-switch set
    // so it is truthful on every route, not only after visiting the dashboard.
    void this.risk.loadKillswitches();
    // Same reasoning for the Live/Offline dot, which also lives in the header on
    // every route: only DashboardComponent used to open the socket, so the dot
    // read "Offline" on Strategies / Risk / Settings / Admin no matter what the
    // stream was actually doing. The shell owns the connection for the whole
    // authenticated session; DashboardWsService is refcounted (C-FE-4/P2-9), so
    // the dashboard attaching and detaching on top of this is safe.
    this.dashboard.start();
  }

  ngOnDestroy(): void {
    // Leaving the shell means signing out or leaving the app — release the
    // shell's reference so the refcount can reach zero and close the socket.
    this.dashboard.stop();
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
