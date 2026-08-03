import { signal } from '@angular/core';
import { TestBed, fakeAsync, tick, discardPeriodicTasks } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { POLL_MS, ScreeningPanelComponent } from './screening-panel.component';
import { ScreenerFacade } from '../../../abstraction/facades/screener.facade';
import { DataProvidersFacade } from '../../../abstraction/facades/data-providers.facade';
import { AuthStore } from '../../../abstraction/stores/auth.store';
import {
  ScreenCriteriaResponse,
  ScreenRunDetail,
} from '../../../core/models/screener.models';

/** Specs assert RAW translation keys — there is no loader in tests. */
describe('ScreeningPanelComponent — M16 §6.6 state ladder', () => {
  let facade: {
    criteria: ReturnType<typeof signal>;
    criteriaError: ReturnType<typeof signal>;
    disabled: ReturnType<typeof signal>;
    loading: ReturnType<typeof signal>;
    runs: ReturnType<typeof signal>;
    loadCriteria: jasmine.Spy;
    loadRuns: jasmine.Spy;
    run: jasmine.Spy;
    runDetail: jasmine.Spy;
  };
  let providers: { keys: ReturnType<typeof signal>; load: jasmine.Spy };

  const READY: ScreenCriteriaResponse = {
    block_present: true,
    criteria: {
      market_cap: { gte: 2_000_000_000 },
      price: { gte: 10, lte: 1000 },
      sector: 'Technology',
      above_sma: [200],
      sma_rising: [200],
      near_52w_high: 25,
      limit: 50,
    },
    fmp_params: { marketCapMoreThan: 2_000_000_000, isActivelyTrading: true, isEtf: false, limit: 50 },
    derived: { above_sma: [200], sma_rising: [200], near_52w_high: 25, min_history: 260 },
  };

  const DONE_RUN: ScreenRunDetail = {
    id: 'run-1',
    status: 'DONE',
    degraded: false,
    error_code: '',
    counts: { vendor_matches: 312, enriched: 50, returned: 1, insufficient_history: 3, skipped_rate_limited: 0, skipped_unavailable: 0 },
    created_at: '2026-08-03T10:00:00Z',
    started_at: '2026-08-03T10:00:01Z',
    finished_at: '2026-08-03T10:00:20Z',
    desc_sha256: 'abc',
    criteria: {},
    results: [{
      symbol: 'NVDA', name: 'NVIDIA Corp', exchange: 'NASDAQ', sector: 'Technology',
      market_cap: 3_200_000_000_000, price: 182.11, volume: 41_000_000, beta: 1.7,
      pct_from_52w_high: 3.2, above_sma_50: true, above_sma_200: true, sma200_rising: true,
    }],
  };

  function setup(opts: {
    criteria?: ScreenCriteriaResponse | null;
    error?: { code: string; message: string; details?: unknown } | null;
    disabled?: boolean;
    fmpConfigured?: boolean;
    staff?: boolean;
    runs?: unknown[];
  } = {}) {
    facade = {
      criteria: signal(opts.criteria ?? READY),
      criteriaError: signal(opts.error ?? null),
      disabled: signal(opts.disabled ?? false),
      loading: signal(false),
      runs: signal(opts.runs ?? []),
      loadCriteria: jasmine.createSpy('loadCriteria').and.resolveTo(undefined),
      loadRuns: jasmine.createSpy('loadRuns').and.resolveTo(undefined),
      run: jasmine.createSpy('run').and.resolveTo({ ok: true, value: { run_id: 'run-1' } }),
      runDetail: jasmine.createSpy('runDetail').and.resolveTo({ ok: true, value: DONE_RUN }),
    };
    providers = {
      keys: signal({
        fmp: { provider: 'FMP', configured: opts.fmpConfigured ?? true, source: 'env' },
        fred: { provider: 'FRED', configured: false, source: null },
      }),
      load: jasmine.createSpy('load').and.resolveTo(undefined),
    };
    TestBed.configureTestingModule({
      imports: [ScreeningPanelComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ScreenerFacade, useValue: facade },
        { provide: DataProvidersFacade, useValue: providers },
        { provide: AuthStore, useValue: { user: signal({ is_staff: opts.staff ?? false }) } },
      ],
    });
    const fixture = TestBed.createComponent(ScreeningPanelComponent);
    fixture.componentRef.setInput('strategyId', 's-1');
    return fixture;
  }

  /** ngOnInit fires on the first detectChanges and is async, so settle after
   *  it and render again before asserting. */
  async function init(fixture: ReturnType<typeof setup>): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function html(fixture: ReturnType<typeof setup>): string {
    return (fixture.nativeElement as HTMLElement).innerHTML;
  }

  // -- State 1 -------------------------------------------------------------
  it('renders NOTHING when the feature flag is off (503)', async () => {
    const fixture = setup({ disabled: true });
    await init(fixture);
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="screening-panel"]')).toBeNull();
  });

  // -- State 2 -------------------------------------------------------------
  it('shows the empty state with a guide link when there is no [screen] block', async () => {
    const fixture = setup({ criteria: { block_present: false } });
    await init(fixture);
    expect(html(fixture)).toContain('screener.empty.heading');
    expect(html(fixture)).toContain('strategy-screening');
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="run-screen"]')).toBeNull();
  });

  // -- State 3 -------------------------------------------------------------
  it('shows line-numbered parse errors verbatim', async () => {
    const fixture = setup({
      criteria: null,
      error: {
        code: 'SCREEN_CRITERIA_INVALID',
        message: 'bad',
        details: [
          { line: 4, error: "Unknown key 'markt_cap'." },
          { line: 6, error: 'price: range is inverted (1000..10).' },
        ],
      },
    });
    await init(fixture);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain("Unknown key 'markt_cap'.");
    expect(text).toContain('range is inverted');
    expect(text).toContain('4');
    expect(text).toContain('6');
  });

  // -- State 4 -------------------------------------------------------------
  it('warns before the click when no FMP key is configured, linking staff to settings', async () => {
    const fixture = setup({ fmpConfigured: false, staff: true });
    await init(fixture);
    expect(html(fixture)).toContain('screener.error.FMP_NOT_CONFIGURED');
    expect(html(fixture)).toContain('/settings/data-providers');
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="run-screen"]')).toBeNull();
  });

  it('gives non-staff the ask-your-administrator copy instead of a link', async () => {
    const fixture = setup({ fmpConfigured: false, staff: false });
    await init(fixture);
    expect(html(fixture)).toContain('data_providers.staff_only');
    expect(html(fixture)).not.toContain('/settings/data-providers');
  });

  // -- State 5 -------------------------------------------------------------
  it('renders criteria chips from the SERVER parse only', async () => {
    const fixture = setup();
    await init(fixture);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Market cap ≥ 2B');
    expect(text).toContain('Sector Technology');
    expect(text).toContain('Above SMA 200');
    expect(text).toContain('SMA 200 rising');
    expect(text).toContain('Within 25% of 52w high');
  });

  it('runs, polls every 2s and renders the results table on completion', fakeAsync(() => {
    const fixture = setup();
    fixture.detectChanges();
    tick();
    fixture.detectChanges();

    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    fixture.detectChanges();

    expect(facade.run).toHaveBeenCalledWith('s-1');
    expect(facade.runDetail).toHaveBeenCalledWith('s-1', 'run-1');

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('NVDA');
    expect(text).toContain('NVIDIA Corp');
    expect(text).toContain('3.2%');
    discardPeriodicTasks();
  }));

  it('STOPS polling once the run reaches a terminal status', fakeAsync(() => {
    const fixture = setup();
    fixture.detectChanges();
    tick();
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    const afterFirst = facade.runDetail.calls.count();
    tick(POLL_MS * 5);
    expect(facade.runDetail.calls.count()).toBe(afterFirst);
    discardPeriodicTasks();
  }));

  it('keeps polling while the run is still RUNNING', fakeAsync(() => {
    const fixture = setup();
    facade.runDetail.and.resolveTo({ ok: true, value: { ...DONE_RUN, status: 'RUNNING' } });
    fixture.detectChanges();
    tick();
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    const afterFirst = facade.runDetail.calls.count();
    tick(POLL_MS * 2);
    expect(facade.runDetail.calls.count()).toBeGreaterThan(afterFirst);
    discardPeriodicTasks();
  }));

  it('stops polling when the component is destroyed', fakeAsync(() => {
    const fixture = setup();
    facade.runDetail.and.resolveTo({ ok: true, value: { ...DONE_RUN, status: 'RUNNING' } });
    fixture.detectChanges();
    tick();
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    fixture.destroy();
    const afterDestroy = facade.runDetail.calls.count();
    tick(POLL_MS * 4);
    expect(facade.runDetail.calls.count()).toBe(afterDestroy);
    discardPeriodicTasks();
  }));

  it('shows the degraded chip with a per-cause counts line', fakeAsync(() => {
    const fixture = setup();
    facade.runDetail.and.resolveTo({
      ok: true,
      value: {
        ...DONE_RUN,
        degraded: true,
        counts: { ...DONE_RUN.counts, skipped_rate_limited: 12, skipped_unavailable: 3, insufficient_history: 2 },
      },
    });
    fixture.detectChanges();
    tick();
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('screener.degraded.chip');
    expect(text).toContain('rate-limited: 12');
    expect(text).toContain('unavailable: 3');       // A4's new cause is surfaced
    expect(text).toContain('insufficient history: 2');
    discardPeriodicTasks();
  }));

  it('renders a translated message for a FAILED run', fakeAsync(() => {
    const fixture = setup();
    facade.runDetail.and.resolveTo({
      ok: true,
      value: { ...DONE_RUN, status: 'FAILED', error_code: 'FMP_UNAVAILABLE', results: [] },
    });
    fixture.detectChanges();
    tick();
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    fixture.detectChanges();
    expect(html(fixture)).toContain('screener.error.FMP_UNAVAILABLE');
    discardPeriodicTasks();
  }));

  it('surfaces a POST-ladder error code from the run action', fakeAsync(() => {
    const fixture = setup();
    facade.run.and.resolveTo({ ok: false, error: { code: 'SCREEN_RUN_ACTIVE', message: 'busy' } });
    fixture.detectChanges();
    tick();
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    fixture.detectChanges();
    expect(html(fixture)).toContain('screener.error.SCREEN_RUN_ACTIVE');
    discardPeriodicTasks();
  }));

  it('surfaces the 429 an 11th run in an hour produces', fakeAsync(() => {
    const fixture = setup();
    facade.run.and.resolveTo({ ok: false, error: { code: 'RATE_LIMITED', message: 'slow down' } });
    fixture.detectChanges();
    tick();
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    fixture.detectChanges();
    expect(html(fixture)).toContain('screener.error.RATE_LIMITED');
    discardPeriodicTasks();
  }));

  it('says so honestly when a completed run matched nothing', fakeAsync(() => {
    const fixture = setup();
    facade.runDetail.and.resolveTo({ ok: true, value: { ...DONE_RUN, results: [] } });
    fixture.detectChanges();
    tick();
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('[data-testid="run-screen"] button')!
      .click();
    tick();
    fixture.detectChanges();
    expect(html(fixture)).toContain('screener.no_matches');
    discardPeriodicTasks();
  }));

  it('resumes polling for a run that was still active on load', fakeAsync(() => {
    const fixture = setup({
      runs: [{ id: 'run-9', status: 'RUNNING', degraded: false, error_code: '', counts: {}, created_at: null, started_at: null, finished_at: null }],
    });
    fixture.detectChanges();
    tick();
    expect(facade.runDetail).toHaveBeenCalledWith('s-1', 'run-9');
    discardPeriodicTasks();
  }));

  it('loads criteria and run history on init', async () => {
    const fixture = setup();
    await init(fixture);
    expect(facade.loadCriteria).toHaveBeenCalledWith('s-1');
    expect(facade.loadRuns).toHaveBeenCalledWith('s-1');
  });
});
