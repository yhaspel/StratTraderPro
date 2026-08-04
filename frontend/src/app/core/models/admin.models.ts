/** Domain types for the M10 Admin Portal. All endpoints live under
 *  `/api/v1/admin/` and use the shared `{ data }` / `{ data, meta }` envelope;
 *  auth (staff + MFA) is enforced server-side. */

/** Server-paginated list metadata (admin users + audit share this shape). */
export interface AdminMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

/** A row in the admin users table. */
export interface AdminUserRow {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  is_staff: boolean;
  is_verified: boolean;
  mfa_enabled: boolean;
  created_at: string;
  broker_count: number;
}

/** A broker connection attached to a user (detail view). */
export interface AdminUserBroker {
  id: string;
  broker: string;
  mode: string;
  status: string;
  account_number: string | null;
  is_default: boolean;
}

/** Full user detail with brokers + recent audit trail. */
export interface AdminUserDetail extends AdminUserRow {
  brokers: AdminUserBroker[];
  recent_audit: AuditRow[];
}

export interface AdminUserListParams {
  q?: string;
  is_active?: boolean;
  has_broker?: boolean;
  page?: number;
}

/** Body for disable / enable / impersonate-start. */
export interface AdminUserActionBody {
  mfa_code: string;
  reason: string;
}

export interface DisableResult {
  id: string;
  is_active: boolean;
  families_revoked: number;
  note: string;
}

export interface EnableResult {
  id: string;
  is_active: boolean;
}

// ---------------------------------------------------------------------------
// Impersonation
// ---------------------------------------------------------------------------

export interface ImpersonationSession {
  token: string;
  session_id: string;
  expires_at: string;
}

export interface ImpersonationStopResult {
  session_id: string;
  stopped: boolean;
  ended_at: string;
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

export interface AuditRow {
  id: string;
  occurred_at: string;
  event_type: string;
  user: string | null;
  actor: string | null;
  entity_type: string | null;
  entity_id: string | null;
  data_before: unknown;
  data_after: unknown;
  ip: string | null;
  ua: string | null;
  self_hash: string;
}

export interface AuditFilters {
  user?: string;
  actor?: string;
  event_type?: string;
  entity_type?: string;
  entity_id?: string;
  occurred_after?: string;
  occurred_before?: string;
  page?: number;
}

// ---------------------------------------------------------------------------
// Platform kill switch
// ---------------------------------------------------------------------------

export interface PlatformHalt {
  reason?: string;
  actor?: string;
  engaged_at?: string;
  [key: string]: unknown;
}

export interface PlatformStatus {
  platform_halted: boolean;
  halt: PlatformHalt | null;
  note: string;
}

export interface KillswitchBody {
  engage: boolean;
  reason: string;
  mfa_code: string;
  /** Required when engage=true — must equal "HALT PLATFORM". */
  confirm?: string;
}

// ---------------------------------------------------------------------------
// Feature flags
// ---------------------------------------------------------------------------

export interface FeatureFlag {
  name: string;
  enabled: boolean;
  source: string;
  mutable: boolean;
  dangerous: boolean;
  description: string;
  default: boolean;
}

export interface FlagToggleBody {
  enabled: boolean;
  mfa_code: string;
  note?: string;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

/** `apps.sentiment.tasks.queue_backlog()` — an OBJECT, not a scalar.
 *
 * BUG: the field was typed `number` and rendered with `{{ h.sentiment_backlog }}`,
 * so the admin Overview + Health cards printed the literal string
 * `[object Object]`. The backend has always returned this shape; the frontend
 * model drifted. Every field is optional because `collect_health()` wraps the
 * section in `_safe(..., {})` — a failing subsystem degrades to `{}` rather
 * than 500-ing the page, and the UI has to render that too. */
export interface SentimentBacklog {
  depth?: number;
  oldest_age_min?: number;
  alert?: boolean;
}

/** `apps.admin_portal.health._active_halts()` — also an object, not a list.
 * Same drift: `active_halts.length` on an object is `undefined`, so the
 * "no active halts" branch never rendered and `@for` got a non-iterable. */
export interface ActiveHalts {
  total?: number;
  platform?: boolean;
}

/** `apps.audit.models.AuditVerifierState` snapshot (`_verifier_state()`). */
export interface AuditVerifierSnapshot {
  last_verified_id?: number | null;
  run_at?: string | null;
  result?: string;
}

export interface AdminHealth {
  queue_depths: Record<string, number>;
  /** `_broker_streams()` returns stream-state -> COUNT of accounts in it
   * (`{"CONNECTED": 1}`), not stream-state -> label. Typed as strings, the card
   * fed the count into a status chip, so the chip said "1" and its tone was
   * resolved from the string "1" rather than from CONNECTED/DEGRADED/DOWN. */
  broker_streams: Record<string, number>;
  hmm_model_age_seconds: number | null;
  /** Optional on the wire in the SPA's view: `collect_health()` guards each
   * section independently, and an older backend may not send it at all. The
   * templates therefore reach it with `?.` — do not "simplify" that away. */
  sentiment_backlog?: SentimentBacklog;
  db_ok: boolean;
  redis_ok: boolean;
  verifier?: AuditVerifierSnapshot;
  active_halts?: ActiveHalts;
  /** `FeatureFlag.objects.count()` — a COUNT, not a list of names. */
  flags_overridden: number;
  /** Whether FMP_API_KEY + FRED_API_KEY are both set, i.e. whether the M06
   * daily regime pipeline can produce observations at all. `false` is why
   * the dashboard's Market Regime card is empty. */
  regime_source_configured?: boolean;
  generated_at: string;
}
