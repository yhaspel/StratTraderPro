/** M08 — Risk profile, sizing decisions, risk events, and kill-switch domain
 *  types. Aligned with the backend risk API. Numeric quantities that come from
 *  Django DecimalField are serialized as strings. */

/** GET/PUT /risk/profile/ — the user's risk envelope. */
export interface RiskProfile {
  risk_per_trade_pct: number;
  max_position_pct: number;
  max_concurrent: number;
  daily_loss_usd: number;
  daily_loss_pct: number;
  leverage_cap: number;
  permitted_asset_classes: string[];
  soft_stop_pct: number;
  hard_stop_pct: number;
  strict_mode: boolean;
  atr_factor: number;
}

/** GET /risk/sizing-decisions/ — one row per pre-trade sizing evaluation. */
export interface SizingDecision {
  id: number;
  order: string | null;
  alert: string | null;
  strategy: string | null;
  symbol: string;
  requested_qty: string;
  computed_qty: string;
  result: 'OK' | 'REJECT';
  reject_reason: string | null;
  inputs: Record<string, unknown>;
  created_at: string;
}

/** GET /risk/events/ — audit trail of risk-relevant occurrences. */
export interface RiskEvent {
  id: number;
  type: string;
  scope: string;
  details: Record<string, unknown>;
  created_at: string;
}

export type KillSwitchScope = 'STRATEGY' | 'USER' | 'PLATFORM';

/** GET /risk/killswitches/ — an active halt. */
export interface KillSwitch {
  id: number;
  scope: KillSwitchScope;
  level: number;
  auto: boolean;
  strategy: string | null;
  reason: string | null;
  created_at: string;
}

/** POST /risk/killswitches/ body — trigger (active=true) or release (active=false). */
export interface SetKillSwitchBody {
  scope: KillSwitchScope;
  target_id?: string;
  active: boolean;
  reason?: string;
  flatten?: boolean;
  mfa_code?: string;
}

/** Optional filters for GET /risk/events/. */
export interface RiskEventParams {
  type?: string;
  from?: string;
  to?: string;
}
