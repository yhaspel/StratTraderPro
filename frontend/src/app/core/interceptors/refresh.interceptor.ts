/**
 * Refresh interceptor — on 401, attempts token refresh.
 * Queues concurrent requests while refresh is in-flight.
 * On failure, logs the user out.
 */
import { HttpInterceptorFn, HttpErrorResponse, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Observable, throwError, from, switchMap, catchError, Subject, filter, take, timeout } from 'rxjs';
import { AuthFacade } from '../../abstraction/facades/auth.facade';
import { AuthStore } from '../../abstraction/stores/auth.store';
import { environment } from '../../../environments/environment';

let isRefreshing = false;
let refreshDone$ = new Subject<boolean>();

// C-FE-4: hard cap on a single refresh attempt. Without it, a hung
// refreshSession() leaves `isRefreshing` true forever and deadlocks every
// subsequent 401 (queued requests never resolve).
const REFRESH_TIMEOUT_MS = 15_000;

// C-FE-1: the refresh flow must NOT run on the *unauthenticated* auth
// endpoints. A 401 there (e.g. wrong login password) is a real credential
// error, not access-token expiry — running refresh would wipe the error the
// user needs to see (facade.logout) or, with a stale refresh token, re-submit
// the POST and double-count the backend lockout. Authenticated /auth/mfa/enroll
// & /auth/mfa/disable are intentionally NOT skipped (they can 401 on expiry).
const SKIP_REFRESH_PATHS = [
  '/auth/login/',
  '/auth/register/',
  '/auth/refresh/',
  '/auth/logout/',
  '/auth/mfa/verify/',
  '/auth/verify-email/',
  '/auth/resend-verification/',
  '/auth/password/reset',
  '/auth/oauth/',
];

export const refreshInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(environment.apiBase)) return next(req);
  if (SKIP_REFRESH_PATHS.some(p => req.url.includes(p))) return next(req);

  const facade = inject(AuthFacade);
  const store = inject(AuthStore);

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status !== 401) return throwError(() => err);

      if (!store.refreshToken()) {
        facade.logout();
        return throwError(() => err);
      }

      if (isRefreshing) {
        // Queue this request until refresh completes
        return refreshDone$.pipe(
          filter(ok => ok !== null as unknown as boolean),
          take(1),
          switchMap(ok => {
            if (!ok) return throwError(() => err);
            return retryWithNewToken(req, next, store);
          }),
        );
      }

      isRefreshing = true;
      refreshDone$ = new Subject<boolean>();

      return from(facade.refreshSession()).pipe(
        timeout(REFRESH_TIMEOUT_MS),
        switchMap(ok => {
          isRefreshing = false;
          refreshDone$.next(ok);
          refreshDone$.complete();
          if (!ok) {
            facade.logout();
            return throwError(() => err);
          }
          return retryWithNewToken(req, next, store);
        }),
        catchError(refreshErr => {
          isRefreshing = false;
          refreshDone$.next(false);
          refreshDone$.complete();
          facade.logout();
          return throwError(() => refreshErr);
        }),
      );
    }),
  );
};

function retryWithNewToken(req: HttpRequest<unknown>, next: HttpHandlerFn, store: AuthStore): Observable<any> {
  const token = store.accessToken();
  const cloned = req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
  return next(cloned);
}
