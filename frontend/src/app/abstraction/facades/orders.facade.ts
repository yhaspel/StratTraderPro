/** OrdersFacade — bridges the OrdersApi + OrdersStore + UI (M05). */
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import { OrderListParams } from '../../core/models/orders.models';
import { OrdersApi } from '../../core/services/orders.api';
import { OrdersStore } from '../stores/orders.store';

@Injectable({ providedIn: 'root' })
export class OrdersFacade {
  private api = inject(OrdersApi);
  private store = inject(OrdersStore);

  readonly orders = this.store.orders;
  readonly meta = this.store.meta;
  readonly filters = this.store.filters;
  readonly selected = this.store.selected;
  readonly reconEvents = this.store.reconEvents;
  readonly loading = this.store.loading;
  readonly error = this.store.error;
  readonly page = this.store.page;
  readonly numPages = this.store.numPages;
  readonly total = this.store.total;

  /** Load a page. When ``filters`` is omitted the last-applied filters are reused
   *  (so prev/next paging keeps the active filter set). */
  async load(page = 1, filters?: OrderListParams): Promise<void> {
    const active = filters ?? this.store.filters();
    this.store.setFilters(active);
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.listOrders({ ...active, page }));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setPage(res.data ?? [], res.meta ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async openDetail(id: string): Promise<void> {
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.getOrder(id));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setSelected(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  closeDetail(): void {
    this.store.setSelected(null);
  }

  /** Downloads the filtered set as a CSV file via a transient object URL. */
  async exportCsv(): Promise<void> {
    try {
      const blob = await firstValueFrom(this.api.exportCsv(this.store.filters()));
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'orders.csv';
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  async loadReconEvents(): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.listReconEvents());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setReconEvents(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  private _asError(err: unknown): ApiError {
    const wrapped = err as { appError?: { apiError?: ApiError; message?: string }; message?: string };
    if (wrapped?.appError?.apiError?.code) {
      return wrapped.appError.apiError;
    }
    return {
      code: 'UNKNOWN',
      message: wrapped?.appError?.message ?? wrapped?.message ?? 'Unknown error',
    };
  }
}
