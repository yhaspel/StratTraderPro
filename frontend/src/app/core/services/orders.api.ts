/** Typed HTTP client for the M04 Orders / Positions / Fills API. */
import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiEnvelope } from '../models/auth.models';
import { Fill, Order, OrderListParams, Position } from '../models/orders.models';

const BASE = `${environment.apiBase}/v1`;

@Injectable({ providedIn: 'root' })
export class OrdersApi {
  private http = inject(HttpClient);

  listOrders(params?: OrderListParams): Observable<ApiEnvelope<Order[]>> {
    let httpParams = new HttpParams();
    if (params?.status) { httpParams = httpParams.set('status', params.status); }
    if (params?.strategy) { httpParams = httpParams.set('strategy', params.strategy); }
    if (params?.symbol) { httpParams = httpParams.set('symbol', params.symbol); }
    return this.http.get<ApiEnvelope<Order[]>>(`${BASE}/orders/`, { params: httpParams });
  }

  listPositions(includeFlat = false): Observable<ApiEnvelope<Position[]>> {
    let httpParams = new HttpParams();
    if (includeFlat) { httpParams = httpParams.set('include_flat', 'true'); }
    return this.http.get<ApiEnvelope<Position[]>>(`${BASE}/positions/`, { params: httpParams });
  }

  listFills(): Observable<ApiEnvelope<Fill[]>> {
    return this.http.get<ApiEnvelope<Fill[]>>(`${BASE}/fills/`);
  }
}
