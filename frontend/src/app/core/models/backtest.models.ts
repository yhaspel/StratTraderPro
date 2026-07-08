/** M09 — Walk-Forward Backtester domain types. Aligned with backend
 *  serializers (apps/backtest/serializers.py) and the report JSON builder
 *  (apps/backtest/report.py). */

/** Run lifecycle status (matches BacktestRun.Status). */
export type BacktestStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'CANCELLING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

/** Coarse worker stage (matches BacktestRun.Stage). */
export type BacktestStage =
  | 'queued'
  | 'loading'
  | 'sweeping'
  | 'replaying'
  | 'reporting';

export type BacktestMode = 'anchored' | 'rolling';
export type BacktestMetric = 'sharpe' | 'sortino' | 'total_return' | 'mar';
export type BacktestSizingMode = 'production' | 'fixed_qty_1';

/** Row in the backtest strategy picker (GET /backtest/strategies/). */
export interface BacktestStrategyOption {
  id: string;
  slug: string;
  name: string;
  is_system: boolean;
  has_adapter: boolean;
}

/** Slippage / commission model (AC-09-1 `costs`). */
export interface BacktestCosts {
  slippage_bps: number;
  per_order_usd: number;
  per_share_usd: number;
  volume_participation_pct: number;
}

/** Parameter sweep grid — a map of param name to the numeric values to try. */
export type BacktestParamGrid = Record<string, number[]>;

/** POST /backtest/runs/ request body (AC-09-1). */
export interface CreateBacktestRunBody {
  strategy: string;
  symbols: string[];
  start: string;
  end: string;
  tf: string;
  train_window_days: number;
  test_window_days: number;
  step_days: number;
  mode: BacktestMode;
  metric: BacktestMetric;
  initial_cash: number;
  param_grid: BacktestParamGrid;
  costs: BacktestCosts;
  sizing_mode: BacktestSizingMode;
  retention_days: number;
}

/** Config echoed back on a run (superset of the create body plus resolved ids). */
export interface BacktestRunConfig {
  strategy_id: string;
  strategy_slug: string;
  symbols: string[];
  start: string;
  end: string;
  tf: string;
  train_window_days: number;
  test_window_days: number;
  step_days: number;
  mode: BacktestMode;
  metric: BacktestMetric;
  initial_cash: number;
  param_grid: BacktestParamGrid;
  costs: BacktestCosts;
  sizing_mode: BacktestSizingMode;
  retention_days: number;
}

/** Per-window walk-forward segment (BacktestSegment). */
export interface BacktestSegment {
  symbol: string;
  window_index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  best_params: Record<string, number>;
  oos_metrics: Record<string, number>;
}

/** Row shape for GET /backtest/runs/. */
export interface BacktestRunRow {
  id: string;
  strategy_slug: string;
  strategy_name: string;
  symbols: string[];
  status: BacktestStatus;
  stage: BacktestStage;
  pct: number;
  metrics_hash: string;
  retention_days: number;
  error_code: string;
  error_message: string;
  worst_pbo: number | null;
  duration_seconds: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** GET /backtest/runs/{id}/ — a row plus config, summary and per-window segments. */
export interface BacktestRunDetail extends BacktestRunRow {
  config: BacktestRunConfig;
  summary: Record<string, unknown>;
  segments: BacktestSegment[];
}

/** Page block returned alongside the runs list. */
export interface BacktestMeta {
  page: number;
  page_size: number;
  total: number;
  num_pages: number;
}

/** Optional filters for GET /backtest/runs/. */
export interface BacktestRunListParams {
  status?: string;
  from?: string;
  to?: string;
  page?: number;
}

/** [iso-timestamp, value] pair used by the equity/drawdown series. */
export type TimeseriesPoint = [string, number];

/** One symbol's slice of the report JSON (apps/backtest/report.py build_json). */
export interface BacktestReportSymbol {
  symbol: string;
  metrics: Record<string, number | null>;
  pbo: number | null;
  sharpe_stability: Record<string, number>;
  windows: BacktestSegment[];
  equity: TimeseriesPoint[];
  drawdown: TimeseriesPoint[];
  trades: unknown[];
}

/** GET /backtest/runs/{id}/report.json (parsed). */
export interface BacktestReport {
  config: BacktestRunConfig;
  symbols: BacktestReportSymbol[];
}

/** Live progress state applied from `backtest.progress` WS frames. */
export interface BacktestProgress {
  pct: number;
  stage: BacktestStage;
  eta_seconds: number | null;
}

/** Report download formats (mirrors the report.* endpoints). */
export type BacktestReportFormat = 'json' | 'html' | 'pdf';
