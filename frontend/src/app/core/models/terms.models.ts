/** Terms re-acceptance state (M11 §7.8). Mirrors GET /api/v1/terms/current/. */
export interface TermsCurrent {
  tos_version: string;
  tos_url: string;
  privacy_version: string;
  privacy_url: string;
  needs_acceptance: boolean;
}

/** Result of POST /api/v1/terms/accept/. */
export interface TermsAcceptResult {
  accepted: boolean;
}
