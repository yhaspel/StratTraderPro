import { TestBed } from '@angular/core/testing';
import {
  HttpClient,
  HttpErrorResponse,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { refreshInterceptor } from './refresh.interceptor';
import { AuthStore } from '../../abstraction/stores/auth.store';
import { AuthFacade } from '../../abstraction/facades/auth.facade';
import { environment } from '../../../environments/environment';

const API = environment.apiBase;

describe('refreshInterceptor', () => {
  let http: HttpClient;
  let controller: HttpTestingController;
  let store: AuthStore;
  let facade: AuthFacade;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([refreshInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    store = TestBed.inject(AuthStore);
    facade = TestBed.inject(AuthFacade);
  });

  afterEach(() => {
    controller.verify();
    localStorage.clear();
  });

  it('does not intercept non-API URLs', (done) => {
    http.get('https://external.example.com/data').subscribe({ error: done.fail, next: () => done() });
    const req = controller.expectOne('https://external.example.com/data');
    req.flush({});
  });

  it('passes through non-401 errors without refresh attempt', (done) => {
    store.setAuthed(
      { id: 'u1', email: 'a@b.com', display_name: 'A', is_verified: true },
      'access', 'refresh'
    );
    http.get(`${API}/some-endpoint`).subscribe({
      error: (err: HttpErrorResponse) => {
        expect(err.status).toBe(403);
        done();
      },
    });
    controller.expectOne(`${API}/some-endpoint`).flush({}, { status: 403, statusText: 'Forbidden' });
  });

  it('logs out when 401 received and no refresh token is stored', (done) => {
    spyOn(facade, 'logout').and.returnValue(Promise.resolve());

    http.get(`${API}/protected`).subscribe({ error: () => done() });

    controller.expectOne(`${API}/protected`).flush({}, { status: 401, statusText: 'Unauthorized' });
  });

  it('retries the request with new access token after successful refresh', (done) => {
    store.setAuthed(
      { id: 'u1', email: 'a@b.com', display_name: 'A', is_verified: true },
      'old-access', 'refresh-tok'
    );
    spyOn(facade, 'refreshSession').and.callFake(async () => {
      store.updateTokens('new-access', 'new-refresh');
      return true;
    });

    http.get(`${API}/protected`).subscribe({
      next: (data: any) => {
        expect(data.ok).toBeTrue();
        done();
      },
      error: done.fail,
    });

    // First request fails with 401
    const first = controller.expectOne(`${API}/protected`);
    first.flush({}, { status: 401, statusText: 'Unauthorized' });

    // Interceptor retries — now with new token
    const retry = controller.expectOne(`${API}/protected`);
    expect(retry.request.headers.get('Authorization')).toBe('Bearer new-access');
    retry.flush({ ok: true });
  });

  it('logs out when refresh itself fails', (done) => {
    store.setAuthed(
      { id: 'u1', email: 'a@b.com', display_name: 'A', is_verified: true },
      'old-access', 'refresh-tok'
    );
    spyOn(facade, 'refreshSession').and.returnValue(Promise.resolve(false));
    spyOn(facade, 'logout').and.returnValue(Promise.resolve());

    http.get(`${API}/protected`).subscribe({
      error: () => {
        expect(facade.logout).toHaveBeenCalled();
        done();
      },
    });

    controller.expectOne(`${API}/protected`).flush({}, { status: 401, statusText: 'Unauthorized' });
  });

  it('queues a second concurrent 401 request while refresh is in-flight', (done) => {
    store.setAuthed(
      { id: 'u1', email: 'a@b.com', display_name: 'A', is_verified: true },
      'old-access', 'refresh-tok'
    );

    let resolveRefresh!: (ok: boolean) => void;
    const refreshPromise = new Promise<boolean>(res => (resolveRefresh = res));
    spyOn(facade, 'refreshSession').and.returnValue(refreshPromise);

    let firstDone = false;
    let secondDone = false;
    const checkBoth = () => { if (firstDone && secondDone) done(); };

    http.get(`${API}/r1`).subscribe({ next: () => { firstDone = true; checkBoth(); }, error: done.fail });
    http.get(`${API}/r2`).subscribe({ next: () => { secondDone = true; checkBoth(); }, error: done.fail });

    // Both fail with 401
    controller.expectOne(`${API}/r1`).flush({}, { status: 401, statusText: 'Unauthorized' });
    controller.expectOne(`${API}/r2`).flush({}, { status: 401, statusText: 'Unauthorized' });

    // Resolve refresh — both retries should fire
    store.updateTokens('new-access', 'new-refresh');
    resolveRefresh(true);

    // Answer both retried requests
    setTimeout(() => {
      controller.match(`${API}/r1`).forEach(r => r.flush({ ok: true }));
      controller.match(`${API}/r2`).forEach(r => r.flush({ ok: true }));
    }, 50);
  });
});
