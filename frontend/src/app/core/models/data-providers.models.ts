/** ADR-062 — instance data-provider key (FMP/FRED) domain types. */

export type DataProvider = 'FMP' | 'FRED';

/** Where the effective key comes from: a key saved in Settings ('ui'), the
 * server environment ('env'), or nowhere (null → the provider is off). */
export type ProviderKeySource = 'ui' | 'env' | null;

export interface ProviderKeyStatus {
  provider: DataProvider;
  configured: boolean;
  source: ProviderKeySource;
  /** Staff-only fields — absent for regular users. */
  hint?: string;
  updated_at?: string | null;
  updated_by?: string | null;
}

/** Payload of GET/PUT/DELETE /api/v1/marketdata/keys/… */
export interface DataProviderKeys {
  fmp: ProviderKeyStatus;
  fred: ProviderKeyStatus;
}
