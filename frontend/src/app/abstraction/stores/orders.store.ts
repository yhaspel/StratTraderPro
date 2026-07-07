/** Signal-based store for the M05 orders feature — server-paginated list,
 *  active filters, selected order detail, and reconciliation events. */
import { Injectable, computed, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import {
  Order,
  OrderListParams,
  OrderWithFills,
  OrdersMeta,
  ReconEvent,
} from '../../core/models/orders.models';

@Injectable({ providedIn: 'root' })
export class OrdersStore {
  private readonly _orders = signal<Order[]>([]);
  private readonly _meta = signal<OrdersMeta | null>(null);
  private readonly _filters = signal<OrderListParams>({});
  private readonly _selected = signal<OrderWithFills | null>(null);
  private readonly _reconEvents = signal<ReconEvent[]>([]);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly orders = this._orders.asReadonly();
  readonly meta = this._meta.asReadonly();
  readonly filters = this._filters.asReadonly();
  readonly selected = this._selected.asReadonly();
  readonly reconEvents = this._reconEvents.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  readonly page = computed(() => this._meta()?.page ?? 1);
  readonly numPages = computed(() => this._meta()?.num_pages ?? 0);
  readonly total = computed(() => this._meta()?.total ?? 0);

  setLoading(loading: boolean) { this._loading.set(loading); }
  setError(err: ApiError | null) { this._error.set(err); }

  setFilters(filters: OrderListParams) { this._filters.set(filters); }

  setPage(orders: Order[], meta: OrdersMeta | null) {
    this._orders.set(orders);
    this._meta.set(meta);
  }

  setSelected(order: OrderWithFills | null) { this._selected.set(order); }

  setReconEvents(events: ReconEvent[]) { this._reconEvents.set(events); }
}
