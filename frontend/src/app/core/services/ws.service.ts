/** Dashboard realtime feed over a native WebSocket.
 *
 * Auth: the daphne endpoint takes the JWT *access* token as a `?token=` query
 * param (WebSocket handshakes can't carry an Authorization header). We read it
 * from the same source the HTTP auth interceptor uses — `AuthStore.accessToken()`.
 *
 * Resilience: exponential-backoff reconnect (capped at ~30s) and a 25s
 * heartbeat `ping` so the server keeps the connection alive.
 */
import { Injectable, inject, signal } from '@angular/core';
import { Subject } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AuthStore } from '../../abstraction/stores/auth.store';

export interface DashboardEvent {
  type: string;
  data?: unknown;
}

const HEARTBEAT_MS = 25_000;
const MAX_BACKOFF_MS = 30_000;

@Injectable({ providedIn: 'root' })
export class DashboardWsService {
  private auth = inject(AuthStore);

  private socket: WebSocket | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private closedByClient = false;
  // C-FE-4: reference-count attached subscribers (dashboard + backtest share
  // this singleton). disconnect() only closes the socket when the LAST
  // subscriber detaches; logout calls forceDisconnect() to tear it down outright.
  private refs = 0;

  private readonly _events = new Subject<DashboardEvent>();
  /** Parsed `{ type, data }` frames from the server. */
  readonly events$ = this._events.asObservable();

  private readonly _connected = signal(false);
  readonly connected = this._connected.asReadonly();

  connect(): void {
    // P2-9: only the PUBLIC connect() mutates the refcount. openSocket() (also
    // called by the reconnect timer) must not, or every reconnect inflates refs
    // so disconnect() can never reach 0 and the socket + heartbeat leak forever.
    this.refs += 1;
    this.openSocket();
  }

  private openSocket(): void {
    // SSR / no-window guard.
    if (typeof window === 'undefined' || typeof WebSocket === 'undefined') { return; }
    if (this.socket &&
        (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const token = this.auth.accessToken();
    if (!token) { return; }

    this.closedByClient = false;
    // P2-10: carry the JWT in the Sec-WebSocket-Protocol subprotocol, not the URL
    // query string (URLs leak into proxy/daphne access logs + browser history).
    const url = `${environment.wsBase}/ws/dashboard/`;
    const ws = new WebSocket(url, ['stp-jwt', token]);
    this.socket = ws;

    ws.onopen = () => {
      this.reconnectAttempts = 0;
      this._connected.set(true);
      this.startHeartbeat();
    };

    ws.onmessage = (ev) => {
      try {
        this._events.next(JSON.parse(ev.data) as DashboardEvent);
      } catch {
        // Ignore malformed frames.
      }
    };

    ws.onerror = () => {
      // Let onclose drive the reconnect flow.
      ws.close();
    };

    ws.onclose = () => {
      this._connected.set(false);
      this.stopHeartbeat();
      // P2-11: don't reconnect if the client closed it OR there's no longer an
      // access token (logged out) — otherwise it loops forever on a dead session.
      if (!this.closedByClient && this.refs > 0 && this.auth.accessToken()) {
        this.scheduleReconnect();
      }
    };
  }

  /** Detach one subscriber. Closes the socket only when the last one leaves. */
  disconnect(): void {
    this.refs = Math.max(0, this.refs - 1);
    if (this.refs > 0) { return; }
    this._close();
  }

  /** Tear the socket down unconditionally (logout — C-FE-4/AC-10.5-3). */
  forceDisconnect(): void {
    this.refs = 0;
    this._close();
  }

  private _close(): void {
    this.closedByClient = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    if (this.socket) {
      this.socket.onclose = null; // prevent a reconnect from the manual close
      this.socket.close();
      this.socket = null;
    }
    this._connected.set(false);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'ping' }));
      }
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = null; }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) { return; }
    const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.reconnectAttempts);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();  // P2-9: reconnect must NOT bump the refcount
    }, delay);
  }
}
