/** Typed HTTP client for the M04/M05 Orders / Positions / Fills / Recon API. */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope, ApiError } from '../models/auth.models';
import {
  Fill,
  Order,
  OrderListParams,
  OrderWithFills,
  OrdersMeta,
  Position,
  ReconEvent,
} from '../models/orders.models';

const BASE = `${environment.apiBase}/v1`;

/** GET /orders/ carries a page ``meta`` block alongside ``data``. */
export interface OrdersListResponse {
  data: Order[];
  meta: OrdersMeta;
  error?: ApiError;
}

@Injectable({ providedIn: 'root' })
export class OrdersApi {
  private http = inject(HttpClient);

  listOrders(params?: OrderListParams): Observable<OrdersListResponse> {
    return this.http.get<OrdersListResponse>(`${BASE}/orders/`, {
      params: this._filterParams(params),
    });
  }

  getOrder(id: string): Observable<ApiEnvelope<OrderWithFills>> {
    return this.http.get<ApiEnvelope<OrderWithFills>>(`${BASE}/orders/${id}/`);
  }

  exportCsv(params?: OrderListParams): Observable<Blob> {
    return this.http.get(`${BASE}/orders/export.csv`, {
      params: this._filterParams(params),
      responseType: 'blob',
    });
  }

  listReconEvents(): Observable<ApiEnvelope<ReconEvent[]>> {
    return this.http.get<ApiEnvelope<ReconEvent[]>>(`${BASE}/reconciliation/events/`);
  }

  listPositions(includeFlat = false): Observable<ApiEnvelope<Position[]>> {
    let httpParams = new HttpParams();
    if (includeFlat) { httpParams = httpParams.set('include_flat', 'true'); }
    return this.http.get<ApiEnvelope<Position[]>>(`${BASE}/positions/`, { params: httpParams });
  }

  listFills(): Observable<ApiEnvelope<Fill[]>> {
    return this.http.get<ApiEnvelope<Fill[]>>(`${BASE}/fills/`);
  }

  /** Builds the shared filter query string for list + CSV export. */
  private _filterParams(params?: OrderListParams): HttpParams {
    let httpParams = new HttpParams();
    if (params?.status) { httpParams = httpParams.set('status', params.status); }
    if (params?.strategy) { httpParams = httpParams.set('strategy', params.strategy); }
    if (params?.symbol) { httpParams = httpParams.set('symbol', params.symbol); }
    if (params?.broker) { httpParams = httpParams.set('broker', params.broker); }
    if (params?.from) { httpParams = httpParams.set('from', params.from); }
    if (params?.to) { httpParams = httpParams.set('to', params.to); }
    if (params?.page) { httpParams = httpParams.set('page', String(params.page)); }
    return httpParams;
  }
}
