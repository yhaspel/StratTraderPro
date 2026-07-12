# ADR-043 — App shell + route structure: one component-ful parent, feature routes as children

**Date:** 2026-07-12
**Status:** Accepted
**Milestone:** M10.5 — App Shell, Navigation, Operability & Review Remediation
**Reference:** `project-plan/10.5-app-shell-and-operability.md` §7.1; AC-10.5-2/-3/-4;
`frontend/src/app/app.routes.ts`, `features/shared/shell/shell.component.ts`,
`features/shared/not-found/not-found.component.ts`,
`core/guards/{auth,landing}.guard.ts`,
`features/{settings,strategies,risk,backtest,admin}/*.routes.ts`

## Context

Through M03–M10 every feature milestone shipped its screens but almost none
wired them to anything clickable. `app.component.ts` was a bare
`<router-outlet />`; the root route rendered an M00 scaffold with zero links;
there was **no logout anywhere** in the codebase; 8 authenticated routes were
reachable only by typing a URL. The old `app.routes.ts` mounted each feature
group via a `path: ''` wrapper with a per-route `canMatch: [authGuard]`, and a
silent `{ path: '**', redirectTo: '' }` dumped unknown URLs on the scaffold.

We needed persistent chrome (header, role-aware nav, user menu with logout, the
impersonation banner, a toast host) on every authenticated screen, without
touching each feature component, and an honest public landing + real 404.

## Decision

**One `ShellComponent` wraps all authenticated routes via a single component-ful
parent route guarded once by `authGuard`.** Public landing and auth pages stay
OUTSIDE the shell.

```
[]  path:'' pathMatch:'full' canMatch:[landingGuard] → LandingComponent   (public)
    path:''                                          → AUTH_ROUTES        (login/register/mfa/oauth…)
    path:'' canMatch:[authGuard] → ShellComponent, children:[
        dashboard, orders, ...SETTINGS, ...STRATEGIES, ...RISK,
        ...BACKTEST, ...ADMIN, help, help/:slug ]
    path:'**' → NotFoundComponent
```

- Each feature `*.routes.ts` was converted from a `path:''`+`loadChildren`
  wrapper into a **plain exported list of child routes** whose paths are
  unchanged (`settings/profile`, `strategies/:id`, `admin/users`, …). The
  redundant per-child `canMatch:[authGuard]` was dropped — the shell parent
  enforces auth **once**. `adminGuard` is **retained** on the admin children
  (the staff gate is separate from the auth gate).
- **`landingGuard`** (mirror of `guestGuard`, scoped to `/`) redirects an authed
  user hitting `/` to `/dashboard`.
- **`authGuard` stays a `CanMatchFn`** returning a `/login?next=…` `UrlTree`.
  Because the shell is component-ful with `canMatch:[authGuard]`, an
  unauthenticated hit on any child path fails the match and is redirected to
  login with the deep-link preserved.

## Why

- **Auth pages/landing must not render nav** (`/login/mfa`, `/oauth/callback`) —
  so they live outside the shell, not inside it.
- **Guard once, not per route** — a single `canMatch` on the parent removes the
  drift where each feature re-declared `authGuard`, and keeps the deep-link
  redirect behavior verified against `auth.guard.ts`.
- **Backtracking gives a real 404** — an *authenticated* unknown path matches the
  shell parent but no child, so the router backtracks to the top-level `**` →
  `NotFoundComponent` (rendered outside the shell). An *anonymous* unknown path
  is intercepted by the shell's `authGuard` `UrlTree` → `/login?next=<path>`.
  Both replace the old silent scaffold redirect (AC-10.5-4). Live-verified
  2026-07-12: anon `/nonexistent` → `/login?next=/nonexistent`.

## Consequences

- The **only** risky change is `app.routes.ts`; rollback = revert the routes
  file + `shell.component` and the app returns to today's (orphaned but
  functional) routes. Feature components are unchanged internally.
- Adding a new authenticated feature is now "add a child route + a nav item",
  not "re-wrap with a guard".
- The shell reads the user from the existing `AuthStore` (no new store, F-11)
  and getting-started state from `OnboardingFacade`.

## Alternatives considered

- **A layout via `<ng-container>`/CSS wrapper in each component** — rejected:
  duplicates chrome across ~10 components and cannot host a single toast/banner.
- **Keeping per-route guards + a shared header component imported everywhere** —
  rejected: the header would still need to be added to every feature, and the
  `**` scaffold-redirect bug would remain.
