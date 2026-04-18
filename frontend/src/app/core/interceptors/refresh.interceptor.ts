/**
 * Refresh interceptor — on 401, attempts token refresh.
 * Queues concurrent requests while refresh is in-flight.
 * On failure, logs the user out.
 */
import { HttpInterceptorFn, HttpErrorResponse, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Observable, throwError, from, switchMap, catchError, Subject, filter, take } from 'rxjs';
import { AuthFacade } from '../../abstraction/facades/auth.facade';
import { AuthStore } from '../../abstraction/stores/auth.store';
import { environment } from '../../../environments/environment';

let isRefreshing = false;
let refreshDone$ = new Subject<boolean>();

export const refreshInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(environment.apiBase)) return next(req);
  // Don't intercept refresh/logout calls themselves
  if (req.url.includes('/auth/refresh/') || req.url.includes('/auth/logout/')) return next(req);

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status !== 401) return throwError(() => err);

      const facade = inject(AuthFacade);
      const store = inject(AuthStore);

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
