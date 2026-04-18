/** Attaches JWT access token to outgoing API requests. */
import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthStore } from '../../abstraction/stores/auth.store';
import { environment } from '../../../environments/environment';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  // Only attach to our own API
  if (!req.url.startsWith(environment.apiBase)) {
    return next(req);
  }

  const store = inject(AuthStore);
  const token = store.accessToken();

  if (token) {
    req = req.clone({
      setHeaders: { Authorization: `Bearer ${token}` },
    });
  }

  return next(req);
};
