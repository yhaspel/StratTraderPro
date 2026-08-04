/** Normalizes HTTP error responses into the AppError shape. */
import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { catchError, throwError } from 'rxjs';
import { ApiError } from '../models/auth.models';

export interface AppError {
  status: number;
  apiError?: ApiError;
  message: string;
}

export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      const appError: AppError = {
        status: err.status,
        message: err.error?.error?.message || err.message || 'Unknown error',
        apiError: err.error?.error,
      };
      // C-FE-3: attach `appError` WITHOUT spreading. Spreading into a plain
      // object destroyed the HttpErrorResponse prototype, so downstream
      // `err instanceof HttpErrorResponse` was always false. Mutate + rethrow
      // the original instance so the prototype (and .error/.status) survive.
      (err as HttpErrorResponse & { appError?: AppError }).appError = appError;
      return throwError(() => err);
    }),
  );
};
