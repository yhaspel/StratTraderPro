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

export interface AdminHealth {
  queue_depths: Record<string, number>;
  broker_streams: Record<string, string>;
  hmm_model_age_seconds: number | null;
  sentiment_backlog: number;
  db_ok: boolean;
  redis_ok: boolean;
  verifier: unknown;
  active_halts: string[];
  flags_overridden: string[];
  generated_at: string;
}
