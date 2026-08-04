/** DashboardFacade — loads the initial snapshot and streams live updates
 *  from the DashboardWsService into the DashboardStore. */
import { Injectable, inject } from '@angular/core';
import { Subscription, firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import { BrokerStatus } from '../../core/models/brokers.models';
import { Fill, Position } from '../../core/models/orders.models';
import { BrokersApi } from '../../core/services/brokers.api';
import { OrdersApi } from '../../core/services/orders.api';
import { DashboardEvent, DashboardWsService } from '../../core/services/ws.service';
import { DashboardStore } from '../stores/dashboard.store';

@Injectable({ providedIn: 'root' })
export class DashboardFacade {
  private ordersApi = inject(OrdersApi);
  private brokersApi = inject(BrokersApi);
  private store = inject(DashboardStore);
  private ws = inject(DashboardWsService);

  private sub: Subscription | null = null;

  readonly positions = this.store.positions;
  readonly fills = this.store.fills;
  readonly brokerStatus = this.store.brokerStatus;
  readonly loading = this.store.loading;
  readonly error = this.store.error;
  readonly connected = this.ws.connected;

  /** Fetch open positions, recent fills, and seed broker status. */
  async loadSnapshot(): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const [positions, fills, brokers] = await Promise.all([
        firstValueFrom(this.ordersApi.listPositions()),
        firstValueFrom(this.ordersApi.listFills()),
        firstValueFrom(this.brokersApi.list()),
      ]);
      const firstErr = positions.error ?? fills.error ?? brokers.error;
      if (firstErr) { this.store.setError(firstErr); return; }
      this.store.setPositions(positions.data ?? []);
      this.store.setFills(fills.data ?? []);
      this.store.setBrokerStatus(
        (brokers.data ?? []).map(b => ({
          id: b.id,
          broker_status: b.status,
          stream_status: b.stream_status,
        })),
      );
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  /** Open the websocket and route its events into the store. */
  start(): void {
    if (this.sub) { return; }
    this.sub = this.ws.events$.subscribe(ev => this._apply(ev));
    this.ws.connect();
  }

  stop(): void {
    this.sub?.unsubscribe();
    this.sub = null;
    this.ws.disconnect();
  }

  private _apply(ev: DashboardEvent): void {
    switch (ev.type) {
      case 'position.updated':
        this.store.applyPosition(ev.data as Position);
        break;
      case 'fill.created':
        this.store.addFill(ev.data as Fill);
        break;
      case 'order.created':
      case 'order.updated':
        // Orders drive positions/fills server-side; the dashboard grid renders
        // those, so order events are intentionally ignored here.
        break;
      case 'broker.status':
        this.store.applyBrokerStatus(ev.data as BrokerStatus);
        break;
      // connection.ack + pong: no-op.
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
