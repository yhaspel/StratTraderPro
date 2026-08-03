/** Strategy screener wire types (M16 §9). */

/** One numeric criterion, either half optional. */
export interface RangeCriterion {
  gte?: number;
  lte?: number;
}

/** The author-facing normalized snapshot the server parsed from `[screen]`. */
export interface ScreenCriteriaMap {
  market_cap?: RangeCriterion;
  price?: RangeCriterion;
  volume?: RangeCriterion;
  beta?: RangeCriterion;
  dividend?: RangeCriterion;
  sector?: string;
  industry?: string;
  exchange?: string;
  country?: string;
  etf?: boolean;
  above_sma?: number[];
  sma_rising?: number[];
  near_52w_high?: number;
  min_history?: number;
  limit?: number;
}

export interface ScreenDerived {
  above_sma?: number[];
  sma_rising?: number[];
  near_52w_high?: number;
  min_history?: number;
}

/** `GET …/screen/criteria/` — parsed server-side ONLY (AC-16-10: no second
 *  parser in TypeScript). */
export interface ScreenCriteriaResponse {
  block_present: boolean;
  criteria?: ScreenCriteriaMap;
  fmp_params?: Record<string, string | number | boolean>;
  derived?: ScreenDerived;
}

/** One line-numbered parse error, as returned in `error.details` for
 *  `SCREEN_CRITERIA_INVALID`. Shown to the author verbatim (§6.6 state 3). */
export interface ScreenCriteriaIssue {
  line: number;
  error: string;
}

export type ScreenRunStatus = 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED';

/** Per-cause counts — every key is always present, so a zero means "none",
 *  never "not measured" (AC-16-7). */
export interface ScreenCounts {
  vendor_matches?: number;
  enriched?: number;
  returned?: number;
  insufficient_history?: number;
  skipped_rate_limited?: number;
  /** A4 — vendor outage, or a per-symbol 4xx (bad/delisted ticker). */
  skipped_unavailable?: number;
}

export interface ScreenResultRow {
  symbol: string;
  name: string;
  exchange: string;
  sector: string;
  market_cap: number | null;
  price: number | null;
  volume: number | null;
  beta: number | null;
  pct_from_52w_high: number | null;
  above_sma_50: boolean | null;
  above_sma_200: boolean | null;
  sma200_rising: boolean | null;
}

export interface ScreenRunSummary {
  id: string;
  status: ScreenRunStatus;
  degraded: boolean;
  error_code: string;
  counts: ScreenCounts;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ScreenRunDetail extends ScreenRunSummary {
  /** A7 — the DESC file's sha256 at run time (NOT a hash of the criteria). */
  desc_sha256: string;
  criteria: {
    criteria?: ScreenCriteriaMap;
    fmp_params?: Record<string, string | number | boolean>;
    derived?: ScreenDerived;
    limit?: number;
  };
  results: ScreenResultRow[];
}

export interface ScreenRunCreated {
  run_id: string;
}

/** A run is finished when it is DONE or FAILED — polling stops here. */
export function isTerminal(status: ScreenRunStatus): boolean {
  return status === 'DONE' || status === 'FAILED';
}
