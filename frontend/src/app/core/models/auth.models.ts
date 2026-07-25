/** Auth + profile + sessions domain types — aligned with backend API envelope. */

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  is_verified: boolean;
  mfa_enabled?: boolean;
  is_staff?: boolean;
}

export interface UserProfile {
  timezone: string;
  language: string;
  notification_email: boolean;
  default_broker_id: string | null;
  terms_version_accepted: string | null;
}

export interface AuthMeResponse extends AuthUser {
  created_at: string;
  profile: UserProfile;
}

export interface AuthTokenPair {
  access: string;
  // P1-4: the refresh token is delivered as an HttpOnly cookie, never read by
  // the SPA. This field is retained only to stay equivalent to the generated
  // OpenAPI schema (the contract spec asserts it); nothing consumes it.
  refresh: string;
  user: AuthUser;
  mfa_required?: boolean;
}

/** Login response when MFA is enrolled — short-lived mfa_token to swap at /auth/mfa/verify/. */
export interface MFAChallenge {
  mfa_required: true;
  mfa_token: string;
}

/**
 * Discriminated at runtime by checking ``data.mfa_required === true``: if so,
 * narrow to MFAChallenge (presence of `mfa_token` rather than `access`).
 * Kept loosely typed so the hand-written shape stays equivalent to the
 * generated OpenAPI ``TokenPairData`` schema.
 */
export type LoginResult = AuthTokenPair | MFAChallenge;

export interface MFAEnrollResponse {
  qr_png_b64: string;
  secret_b32: string;
  otpauth_uri: string;
}

export interface MFAEnrollConfirmResponse {
  backup_codes: string[];
}

export interface Session {
  family_id: string;
  created_at: string;
  last_used_at: string | null;
  ip_masked: string | null;
  device: string;
  current: boolean;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, string[]>;
}

export interface ApiEnvelope<T> {
  data?: T;
  error?: ApiError;
}

export type AuthStatus = 'idle' | 'loading' | 'error' | 'authed' | 'mfa_pending';
