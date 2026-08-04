import { TestBed } from '@angular/core/testing';
import {
  HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors,
} from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { errorInterceptor, AppError } from './error.interceptor';
import { environment } from '../../../environments/environment';

describe('errorInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
  });

  afterEach(() => controller.verify());

  it('attaches appError WITHOUT destroying the HttpErrorResponse prototype (C-FE-3)', (done) => {
    http.get(`${environment.apiBase}/x`).subscribe({
      error: (err: HttpErrorResponse & { appError?: AppError }) => {
        expect(err instanceof HttpErrorResponse).toBeTrue();
        expect(err.appError?.status).toBe(400);
        expect(err.appError?.apiError?.code).toBe('VALIDATION_ERROR');
        expect(err.appError?.message).toBe('bad input');
        done();
      },
    });
    controller.expectOne(`${environment.apiBase}/x`).flush(
      { error: { code: 'VALIDATION_ERROR', message: 'bad input' } },
      { status: 400, statusText: 'Bad Request' },
    );
  });
});
