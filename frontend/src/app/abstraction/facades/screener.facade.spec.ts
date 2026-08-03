import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ScreenerFacade } from './screener.facade';
import { errorInterceptor } from '../../core/interceptors/error.interceptor';
import { environment } from '../../../environments/environment';
import { ScreenCriteriaIssue } from '../../core/models/screener.models';

/**
 * The facade is what turns HTTP outcomes into the panel's five states, so it is
 * exercised through the REAL error interceptor and a real HttpClient — the panel
 * spec stubs the facade, which would otherwise leave this mapping unproven.
 */
describe('ScreenerFacade', () => {
  const ID = 's-1';
  const base = `${environment.apiBase}/v1/strategies/${ID}/screen`;
  let facade: ScreenerFacade;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    facade = TestBed.inject(ScreenerFacade);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('stores the parsed criteria on success', async () => {
    const promise = facade.loadCriteria(ID);
    http.expectOne(`${base}/criteria/`).flush({ data: { block_present: true, limit: 50 } });
    await promise;
    expect(facade.criteria()?.block_present).toBeTrue();
    expect(facade.criteriaError()).toBeNull();
    expect(facade.disabled()).toBeFalse();
  });

  it('records block_present:false as a normal state, not an error', async () => {
    const promise = facade.loadCriteria(ID);
    http.expectOne(`${base}/criteria/`).flush({ data: { block_present: false } });
    await promise;
    expect(facade.criteria()?.block_present).toBeFalse();
    expect(facade.criteriaError()).toBeNull();
  });

  it('preserves the line-numbered details of a 400 SCREEN_CRITERIA_INVALID', async () => {
    const details: ScreenCriteriaIssue[] = [
      { line: 4, error: "Unknown key 'markt_cap'." },
      { line: 7, error: 'price: range is inverted (1000..10).' },
    ];
    const promise = facade.loadCriteria(ID);
    http.expectOne(`${base}/criteria/`).flush(
      { error: { code: 'SCREEN_CRITERIA_INVALID', message: 'bad block', details } },
      { status: 400, statusText: 'Bad Request' },
    );
    await promise;

    const err = facade.criteriaError();
    expect(err?.code).toBe('SCREEN_CRITERIA_INVALID');
    // The detail payload must survive the interceptor untouched — it IS the
    // author-facing lint output.
    expect(err?.details as unknown as ScreenCriteriaIssue[]).toEqual(details);
    expect(facade.disabled()).toBeFalse();
  });

  it('sets disabled (not an error) on a 503 from the criteria endpoint', async () => {
    const promise = facade.loadCriteria(ID);
    http.expectOne(`${base}/criteria/`).flush(
      { error: { code: 'FEATURE_DISABLED', message: 'off' } },
      { status: 503, statusText: 'Service Unavailable' },
    );
    await promise;
    expect(facade.disabled()).toBeTrue();
    expect(facade.criteriaError()).toBeNull(); // the panel hides; nothing to show
  });

  it('sets disabled on a 503 from ANY screener endpoint, not just criteria', async () => {
    const promise = facade.loadRuns(ID);
    http.expectOne(`${base}/runs/?limit=5`).flush(
      { error: { code: 'FEATURE_DISABLED', message: 'off' } },
      { status: 503, statusText: 'Service Unavailable' },
    );
    await promise;
    expect(facade.disabled()).toBeTrue();
  });

  it('maps a 404 to a plain error without hiding the panel', async () => {
    const promise = facade.loadCriteria(ID);
    http.expectOne(`${base}/criteria/`).flush(
      { error: { code: 'STRATEGY_NOT_FOUND', message: 'gone' } },
      { status: 404, statusText: 'Not Found' },
    );
    await promise;
    expect(facade.criteriaError()?.code).toBe('STRATEGY_NOT_FOUND');
    expect(facade.disabled()).toBeFalse();
  });

  it('returns the run id on a 202', async () => {
    const promise = facade.run(ID);
    http.expectOne(`${base}/`).flush({ data: { run_id: 'r-1' } }, { status: 202, statusText: 'Accepted' });
    const res = await promise;
    expect(res.ok).toBeTrue();
    if (res.ok) {
      expect(res.value.run_id).toBe('r-1');
    }
  });

  it('surfaces each POST-ladder code as a Result error', async () => {
    for (const [status, code] of [
      [409, 'FMP_NOT_CONFIGURED'],
      [409, 'NO_SCREEN_CRITERIA'],
      [409, 'SCREEN_RUN_ACTIVE'],
      [429, 'RATE_LIMITED'],
    ] as [number, string][]) {
      const promise = facade.run(ID);
      http.expectOne(`${base}/`).flush(
        { error: { code, message: code } },
        { status, statusText: 'err' },
      );
      const res = await promise;
      expect(res.ok).withContext(code).toBeFalse();
      if (!res.ok) {
        expect(res.error.code).toBe(code);
      }
    }
  });

  it('requests the run list with the limit it was given', async () => {
    const promise = facade.loadRuns(ID, 3);
    http.expectOne(`${base}/runs/?limit=3`).flush({ data: [] });
    await promise;
    expect(facade.runs()).toEqual([]);
  });

  it('returns the full run detail including desc_sha256 and criteria', async () => {
    const promise = facade.runDetail(ID, 'r-1');
    http.expectOne(`${base}/runs/r-1/`).flush({
      data: { id: 'r-1', status: 'DONE', desc_sha256: 'abc', criteria: {}, results: [] },
    });
    const res = await promise;
    expect(res.ok).toBeTrue();
    if (res.ok) {
      expect(res.value.desc_sha256).toBe('abc');
      expect(res.value.criteria).toBeDefined();
    }
  });

  it('falls back to UNKNOWN rather than throwing on a bodyless failure', async () => {
    const promise = facade.run(ID);
    http.expectOne(`${base}/`).flush(null, { status: 500, statusText: 'Server Error' });
    const res = await promise;
    expect(res.ok).toBeFalse();
    if (!res.ok) {
      expect(res.error.code).toBe('UNKNOWN');
    }
  });
});
