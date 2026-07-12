/** Onboarding checklist state (M10.5 §9). Mirrors GET /api/v1/onboarding/status/. */
export interface OnboardingStatus {
  mfa_enrolled: boolean;
  broker_connected: boolean;
  strategy_ready: boolean;
  first_fill_seen: boolean;
  complete: boolean;
}
