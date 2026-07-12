/** TermsApi — request shape for the M11 §7.8 re-acceptance endpoints. */
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { TermsApi } from './terms.api';
import { TermsCurrent } from '../models/terms.models';

const BASE = 'http://localhost:8777/api/v1';

describe('TermsApi', () => {
  let api: TermsApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(TermsApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('current() GETs /terms/current/ and returns the envelope', () => {
    const payload: TermsCurrent = {
      tos_version: '2026-07-01',
      tos_url: 'https://example.test/tos',
      privacy_version: '2026-07-01',
      privacy_url: 'https://example.test/privacy',
      needs_acceptance: true,
    };
    let received: TermsCurrent | undefined;
    api.current().subscribe((res) => (received = res.data));

    const req = http.expectOne(`${BASE}/terms/current/`);
    expect(req.request.method).toBe('GET');
    req.flush({ data: payload });

    expect(received).toEqual(payload);
  });

  it('accept() POSTs the tos + privacy versions to /terms/accept/', () => {
    let accepted: boolean | undefined;
    api.accept('2026-07-01', '2026-06-15').subscribe((res) => (accepted = res.data?.accepted));

    const req = http.expectOne(`${BASE}/terms/accept/`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ tos_version: '2026-07-01', privacy_version: '2026-06-15' });
    req.flush({ data: { accepted: true } });

    expect(accepted).toBeTrue();
  });
});
