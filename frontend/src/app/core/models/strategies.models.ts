/** M03 — Strategy + WebhookConfig domain types. Aligned with backend serializers. */

export type StrategyType = 'system' | 'user';

export interface StrategyFileSummary {
  kind: 'PINE' | 'DESC' | 'WEBHOOK_TEMPLATE';
  filename: string;
  sha256: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface Strategy {
  id: string;
  name: string;
  slug: string;
  description_short: string;
  is_system: boolean;
  is_enabled: boolean;
  is_community_tested: boolean;
  type: StrategyType;
  has_webhook_config: boolean;
  created_at: string;
  updated_at: string;
  files: StrategyFileSummary[];
}

/** Payload returned by GET /strategies/{id}/webhook-config/ and POST /rotate/.
 * `secret` is non-null ONLY in the response that creates the row OR rotates it.
 * Frontend is responsible for storing it transiently and never persisting.
 */
export interface WebhookConfig {
  id?: string;
  version: number;
  json_schema: Record<string, unknown>;
  payload_template: Record<string, unknown>;
  url: string;
  secret: string | null;
  reveal_once: boolean;
  created_at?: string;
  rotated_at?: string | null;
  updated_at?: string;
}

export interface WebhookRotateResponse {
  url: string;
  secret: string;          // reveal-once
  version: number;
  rotated_at: string;
  reveal_once: true;
}

/** Wizard payload — used by the upload facade. */
export interface StrategyUploadPayload {
  pine: File;
  description: File;
  webhook: File;
  acceptUntestedRisk: true;
}

/** Result of a dry-run validation against the user's stored schema. */
export interface WebhookDryRunResult {
  valid: boolean;
}
