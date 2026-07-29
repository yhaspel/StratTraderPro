/** M06 — Market-data regime domain types. Aligned with the backend regime API.
 *  Numeric fields (scores, z-scores, probabilities) are serialized as JSON
 *  numbers here (unlike the Decimal string fields on the orders domain). */

export type RegimeLabel = 'BULL' | 'CHOP' | 'BEAR' | 'CRISIS' | 'NEUTRAL';
export type RegimeRuleBucket = 'RISK_ON' | 'NEUTRAL' | 'RISK_OFF' | 'PANIC';

/** A single contributing feature and its standardized (z) score. */
export interface TopFeature {
  name: string;
  z: number;
}

/** Model reference attached to each observation. */
export interface RegimeModelRef {
  version: string;
  degraded: boolean;
}

/** A regime observation for a scope (e.g. MARKET) at a point in time. */
export interface RegimeObservation {
  ts: string;
  scope: string;
  label: RegimeLabel;
  rule_bucket: RegimeRuleBucket;
  rule_score: number;
  hmm_state: number | null;
  hmm_probs: Record<string, number>;
  top_features: TopFeature[];
  model: RegimeModelRef;
}

/** GET /regime/model/ — the trained HMM currently in service. */
export interface RegimeModelActive {
  version: string;
  n_states: number;
  trained_at: string;
  holdout_ll: number;
  degraded: boolean;
  /** Both FMP_API_KEY and FRED_API_KEY are set, so the daily feature pipeline
   * can actually produce observations. Absent on older backends. */
  source_configured?: boolean;
}

/** GET /regime/model/ — no trained model available; rule-based fallback only. */
export interface RegimeModelDegraded {
  active: null;
  degraded: true;
  source_configured?: boolean;
}

export type RegimeModelInfo = RegimeModelActive | RegimeModelDegraded;
