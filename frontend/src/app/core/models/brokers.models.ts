/** M04 — Broker account domain types. Aligned with backend brokers API. */

export type BrokerName = 'ALPACA';
export type BrokerMode = 'PAPER' | 'LIVE';

/** Realtime stream health as reported by the backend. */
export type StreamStatus = 'CONNECTED' | 'DEGRADED' | 'DOWN';

export interface BrokerAccount {
  id: string;
  broker: string;
  mode: string;
  account_number: string | null;
  nickname: string | null;
  is_default: boolean;
  status: string;
  stream_status: StreamStatus;
  last_connected_at: string | null;
  created_at: string;
}

/** Body for POST /brokers/ — connect an Alpaca paper account. */
export interface BrokerConnectPayload {
  api_key_id: string;
  api_secret: string;
  broker: BrokerName;
  mode: BrokerMode;
  nickname?: string;
  is_default?: boolean;
}

/** POST /brokers/ response — the created account plus its buying power. */
export interface BrokerConnectResult extends BrokerAccount {
  buying_power: string;
}

/** POST /brokers/{id}/test-connection/ response. */
export interface BrokerTestConnectionResult {
  account_number: string;
  buying_power: string;
  cash: string;
  currency: string;
  status: string;
}

/** GET /brokers/{id}/status/ response. */
export interface BrokerStatus {
  id: string;
  broker_status: string;
  stream_status: StreamStatus;
}

/** POST /brokers/{id}/flatten/ response (admin only). */
export interface BrokerFlattenResult {
  flattened: number;
  reason: string;
}
