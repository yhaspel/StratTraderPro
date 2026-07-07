/** M04 — Order / Position / Fill domain types. Aligned with backend serializers.
 *  Numeric fields are serialized as strings (Django DecimalField). */

export interface Order {
  id: string;
  client_order_id: string | null;
  broker_order_id: string | null;
  symbol: string;
  side: string;
  qty: string;
  filled_qty: string;
  order_type: string;
  limit_price: string | null;
  time_in_force: string;
  status: string;
  reason: string | null;
  strategy: string | null;
  broker_account: string | null;
  created_at: string;
  updated_at: string;
}

export interface Position {
  id: string;
  symbol: string;
  qty: string;
  avg_cost: string;
  market_price: string | null;
  unrealized_pnl: string | null;
  broker_account: string | null;
  updated_at: string;
}

export interface Fill {
  id: string;
  order: string | null;
  symbol: string;
  qty: string;
  price: string;
  ts: string;
  broker_exec_id: string | null;
  created_at: string;
}

/** Optional filters for GET /orders/. */
export interface OrderListParams {
  status?: string;
  strategy?: string;
  symbol?: string;
}
