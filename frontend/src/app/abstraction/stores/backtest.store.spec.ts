import { TestBed } from '@angular/core/testing';
import { BacktestStore } from './backtest.store';
import {
  BacktestRunConfig,
  BacktestRunRow,
} from '../../core/models/backtest.models';

function _row(overrides: Partial<BacktestRunRow> = {}): BacktestRunRow {
  return {
    id: overrides.id ?? 'r1',
    strategy_slug: 'sma-cross-demo',
    strategy_name: 'SMA Cross',
    symbols: ['AAPL'],
    status: overrides.status ?? 'QUEUED',
    stage: overrides.stage ?? 'queued',
    pct: overrides.pct ?? 0,
    metrics_hash: '',
    retention_days: 90,
    error_code: '',
    error_message: '',
    worst_pbo: null,
    duration_seconds: null,
    created_at: '2026-07-08T00:00:00Z',
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

describe('BacktestStore', () => {
  let store: BacktestStore;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    store = TestBed.inject(BacktestStore);
  });

  it('starts empty', () => {
    expect(store.runs().length).toBe(0);
    expect(store.page()).toBe(1);
    expect(store.numPages()).toBe(0);
    expect(store.report()).toBeNull();
  });

  it('setPage stores rows + meta and derives page/total', () => {
    store.setPage([_row({ id: 'a' }), _row({ id: 'b' })], {
      page: 2, page_size: 25, total: 40, num_pages: 2,
    });
    expect(store.runs().map(r => r.id)).toEqual(['a', 'b']);
    expect(store.page()).toBe(2);
    expect(store.numPages()).toBe(2);
    expect(store.total()).toBe(40);
  });

  it('applyProgress records the frame and patches the matching row', () => {
    store.setPage([_row({ id: 'r1' })], null);
    store.applyProgress('r1', { pct: 42, stage: 'sweeping', eta_seconds: 12 });
    expect(store.progress()['r1'].pct).toBe(42);
    const row = store.runs().find(r => r.id === 'r1')!;
    expect(row.pct).toBe(42);
    expect(row.stage).toBe('sweeping');
  });

  it('applyProgress is a no-op on the list when the row is absent', () => {
    store.applyProgress('ghost', { pct: 10, stage: 'loading', eta_seconds: null });
    expect(store.progress()['ghost'].pct).toBe(10);
    expect(store.runs().length).toBe(0);
  });

  it('patchStatus updates the list row and the open detail', () => {
    store.setPage([_row({ id: 'r1', status: 'RUNNING' })], null);
    store.setSelected({
      ..._row({ id: 'r1', status: 'RUNNING' }),
      config: {} as BacktestRunConfig,
      summary: {},
      segments: [],
    });
    store.patchStatus('r1', 'COMPLETED');
    expect(store.runs()[0].status).toBe('COMPLETED');
    expect(store.selected()!.status).toBe('COMPLETED');
  });

  it('rerunConfig round-trips', () => {
    const cfg = { strategy_slug: 'x', symbols: ['AAPL'] } as unknown as BacktestRunConfig;
    store.setRerunConfig(cfg);
    expect(store.rerunConfig()).toBe(cfg);
    store.setRerunConfig(null);
    expect(store.rerunConfig()).toBeNull();
  });
});
