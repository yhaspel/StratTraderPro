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
      return throwError(() => ({ ...err, appError }));
    }),
  );
};
