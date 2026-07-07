/** Signal-based store for the live dashboard.
 *
 * Positions are keyed by id (a flat position — qty 0 — is dropped so the grid
 * only shows open exposure). Fills are a capped, newest-first feed. Broker
 * status is keyed by broker-account id. */
import { Injectable, computed, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import { BrokerStatus } from '../../core/models/brokers.models';
import { Fill, Position } from '../../core/models/orders.models';

const MAX_FILLS = 200;

@Injectable({ providedIn: 'root' })
export class DashboardStore {
  private readonly _positions = signal<Record<string, Position>>({});
  private readonly _fills = signal<Fill[]>([]);
  private readonly _brokerStatus = signal<Record<string, BrokerStatus>>({});
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly positions = computed(() =>
    Object.values(this._positions()).sort((a, b) => a.symbol.localeCompare(b.symbol)),
  );
  readonly fills = this._fills.asReadonly();
  readonly brokerStatus = computed(() => Object.values(this._brokerStatus()));
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  setLoading(loading: boolean) { this._loading.set(loading); }
  setError(err: ApiError | null) { this._error.set(err); }

  setPositions(positions: Position[]) {
    const map: Record<string, Position> = {};
    for (const p of positions) { map[p.id] = p; }
    this._positions.set(map);
  }

  /** Upsert a position; a flat position (qty 0) is removed from the open grid. */
  applyPosition(position: Position) {
    const next = { ...this._positions() };
    if (Number(position.qty) === 0) {
      delete next[position.id];
    } else {
      next[position.id] = position;
    }
    this._positions.set(next);
  }

  setFills(fills: Fill[]) {
    this._fills.set([...fills].slice(0, MAX_FILLS));
  }

  addFill(fill: Fill) {
    this._fills.set([fill, ...this._fills()].slice(0, MAX_FILLS));
  }

  setBrokerStatus(statuses: BrokerStatus[]) {
    const map: Record<string, BrokerStatus> = {};
    for (const s of statuses) { map[s.id] = s; }
    this._brokerStatus.set(map);
  }

  applyBrokerStatus(status: BrokerStatus) {
    this._brokerStatus.set({ ...this._brokerStatus(), [status.id]: status });
  }

  reset() {
    this._positions.set({});
    this._fills.set([]);
    this._brokerStatus.set({});
    this._error.set(null);
  }
}
