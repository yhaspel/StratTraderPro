/** M04/M05 — Order / Position / Fill / Reconciliation domain types. Aligned with
 *  backend serializers. Numeric fields are serialized as strings (Django
 *  DecimalField). */

export interface Order {
  id: string;
  client_order_id: string | null;
  broker_order_id: string | null;
  symbol: string;
  asset_class: string;
  side: string;
  qty: string;
  filled_qty: string;
  order_type: string;
  limit_price: string | null;
  stop_price: string | null;
  time_in_force: string;
  option_expiry: string | null;
  option_strike: string | null;
  option_right: string | null;
  future_root: string | null;
  future_expiry: string | null;
  status: string;
  reason: string | null;
  strategy: string | null;
  broker_account: string | null;
  broker: string | null;
  created_at: string;
  updated_at: string;
}

/** GET /orders/{id}/ — order plus its lifecycle fills. */
export interface OrderWithFills extends Order {
  fills: Fill[];
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

/** Reconciliation drift/heal event (M05). */
export interface ReconEvent {
  id: number;
  broker_account: string | null;
  symbol: string;
  asset_class: string;
  kind: string; // DRIFT | HEAL | RESOLVED
  our_qty: string;
  broker_qty: string;
  detail: string;
  created_at: string;
  resolved_at: string | null;
}

/** Page block returned alongside the orders list. */
export interface OrdersMeta {
  page: number;
  page_size: number;
  total: number;
  num_pages: number;
}

/** Normalized orders page held in the store. */
export interface OrdersPage {
  items: Order[];
  meta: OrdersMeta;
}

/** Optional filters for GET /orders/ (and /orders/export.csv). */
export interface OrderListParams {
  status?: string;
  strategy?: string;
  symbol?: string;
  broker?: string;
  from?: string;
  to?: string;
  page?: number;
}
