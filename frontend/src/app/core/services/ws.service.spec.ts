import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { DashboardWsService } from './ws.service';
import { AuthStore } from '../../abstraction/stores/auth.store';

/** Minimal fake WebSocket so we can drive open/close without a real socket. */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  closed = false;
  constructor(public url: string, public protocols?: string[]) {
    FakeWebSocket.instances.push(this);
  }
  send(): void { /* noop */ }
  close(): void { this.closed = true; this.readyState = 3; this.onclose?.(); }
}

describe('DashboardWsService — refcount + auth (P2-9/P2-10)', () => {
  let svc: DashboardWsService;
  let realWs: typeof WebSocket;

  beforeEach(() => {
    realWs = (window as unknown as { WebSocket: typeof WebSocket }).WebSocket;
    FakeWebSocket.instances = [];
    (window as unknown as { WebSocket: unknown }).WebSocket = FakeWebSocket;
    TestBed.configureTestingModule({
      providers: [
        DashboardWsService,
        { provide: AuthStore, useValue: { accessToken: signal('tok-123') } },
      ],
    });
    svc = TestBed.inject(DashboardWsService);
  });

  afterEach(() => {
    (window as unknown as { WebSocket: typeof WebSocket }).WebSocket = realWs;
  });

  function refs(): number {
    return (svc as unknown as { refs: number }).refs;
  }

  it('carries the JWT in the subprotocol, not the URL', () => {
    svc.connect();
    const ws = FakeWebSocket.instances[0];
    expect(ws.url).not.toContain('token=');
    expect(ws.protocols).toEqual(['stp-jwt', 'tok-123']);
  });

  it('reconnect does not inflate the refcount; disconnect reaches 0', () => {
    svc.connect();
    expect(refs()).toBe(1);
    const first = FakeWebSocket.instances[0];
    first.readyState = FakeWebSocket.OPEN;
    first.onopen?.();
    // Simulate an unexpected drop → reconnect fires openSocket(), NOT connect().
    first.readyState = 3;
    first.onclose?.();
    // A single subscriber → one ref regardless of reconnects.
    expect(refs()).toBe(1);
    svc.disconnect();
    expect(refs()).toBe(0);
  });

  it('does not reconnect once there is no access token (logged out)', () => {
    svc.connect();
    const ws = FakeWebSocket.instances[0];
    ws.readyState = FakeWebSocket.OPEN;
    ws.onopen?.();
    // Simulate logout clearing the token, then an unexpected close.
    (TestBed.inject(AuthStore).accessToken as unknown as { set(v: string | null): void }).set(null);
    const before = FakeWebSocket.instances.length;
    ws.readyState = 3;
    ws.onclose?.();
    expect(FakeWebSocket.instances.length).toBe(before); // no new socket scheduled
  });
});
