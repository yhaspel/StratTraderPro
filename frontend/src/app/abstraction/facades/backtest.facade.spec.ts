import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { Subject, of } from 'rxjs';
import { BacktestFacade } from './backtest.facade';
import { BacktestApi } from '../../core/services/backtest.api';
import { DashboardEvent, DashboardWsService } from '../../core/services/ws.service';
import { BacktestRunDetail } from '../../core/models/backtest.models';

function _detail(overrides: Partial<BacktestRunDetail> = {}): BacktestRunDetail {
  return {
    id: overrides.id ?? 'r1',
    strategy_slug: 'sma-cross-demo',
    strategy_name: 'SMA Cross',
    symbols: ['AAPL'],
    status: overrides.status ?? 'QUEUED',
    stage: 'queued',
    pct: 0,
    metrics_hash: '',
    retention_days: 90,
    error_code: '',
    error_message: '',
    worst_pbo: null,
    duration_seconds: null,
    created_at: '2026-07-08T00:00:00Z',
    started_at: null,
    finished_at: null,
    config: {
      strategy_id: 's1', strategy_slug: 'sma-cross-demo', symbols: ['AAPL'],
      start: '2023-01-01', end: '2026-01-01', tf: '1d',
      train_window_days: 252, test_window_days: 63, step_days: 63,
      mode: 'rolling', metric: 'sharpe', initial_cash: 100000,
      param_grid: {}, costs: { slippage_bps: 5, per_order_usd: 0, per_share_usd: 0, volume_participation_pct: 10 },
      sizing_mode: 'production', retention_days: 90,
    },
    summary: {},
    segments: [],
    ...overrides,
  };
}

describe('BacktestFacade', () => {
  let facade: BacktestFacade;
  let events: Subject<DashboardEvent>;
  let api: jasmine.SpyObj<Pick<BacktestApi, 'createRun' | 'reportBlob' | 'getRun'>>;

  beforeEach(() => {
    events = new Subject<DashboardEvent>();
    api = jasmine.createSpyObj('BacktestApi', ['createRun', 'reportBlob', 'getRun']);
    const wsMock = {
      events$: events.asObservable(),
      connect: jasmine.createSpy('connect'),
      disconnect: jasmine.createSpy('disconnect'),
      connected: signal(false).asReadonly(),
    };

    TestBed.configureTestingModule({
      providers: [
        BacktestFacade,
        { provide: BacktestApi, useValue: api },
        { provide: DashboardWsService, useValue: wsMock },
      ],
    });
    facade = TestBed.inject(BacktestFacade);
  });

  it('submitRun returns ok with the created run detail', async () => {
    const run = _detail({ id: 'new-run' });
    api.createRun.and.returnValue(of({ data: run }));

    const res = await facade.submitRun({} as never);

    expect(res.ok).toBeTrue();
    if (res.ok) { expect(res.value.id).toBe('new-run'); }
    expect(api.createRun).toHaveBeenCalled();
  });

  it('submitRun surfaces an API error envelope', async () => {
    api.createRun.and.returnValue(of({ error: { code: 'BACKTEST_NO_ADAPTER', message: 'no adapter' } }));

    const res = await facade.submitRun({} as never);

    expect(res.ok).toBeFalse();
    if (!res.ok) { expect(res.error.code).toBe('BACKTEST_NO_ADAPTER'); }
  });

  it('applies a backtest.progress websocket frame into the store', () => {
    facade.start();
    events.next({ type: 'backtest.progress', data: { run_id: 'r1', pct: 42, stage: 'sweeping', eta_seconds: 12 } });

    expect(facade.progress()['r1']).toEqual({ pct: 42, stage: 'sweeping', eta_seconds: 12 });
  });

  it('ignores non-backtest websocket frames', () => {
    facade.start();
    events.next({ type: 'position.updated', data: { run_id: 'r1', pct: 99 } });

    expect(facade.progress()['r1']).toBeUndefined();
  });

  it('downloadReport pulls the blob and clicks a transient anchor', async () => {
    api.reportBlob.and.returnValue(of(new Blob(['{}'], { type: 'application/json' })));
    const anchor = document.createElement('a');
    spyOn(anchor, 'click');
    spyOn(document, 'createElement').and.returnValue(anchor);
    spyOn(URL, 'createObjectURL').and.returnValue('blob:mock');
    spyOn(URL, 'revokeObjectURL');

    await facade.downloadReport('r1', 'json');

    expect(api.reportBlob).toHaveBeenCalledWith('r1', 'json');
    expect(anchor.click).toHaveBeenCalled();
    expect(anchor.download).toBe('backtest-r1.json');
  });
});
