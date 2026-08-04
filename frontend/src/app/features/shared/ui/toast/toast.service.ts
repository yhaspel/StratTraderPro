/** Global toast queue (M10.5 §7.4). Signal-backed; the host renders once in the
 * ShellComponent. Errors are `role="alert"`/assertive; success/info are polite. */
import { Injectable, signal } from '@angular/core';

export type ToastKind = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

const AUTO_DISMISS_MS = 6000;

@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly _toasts = signal<Toast[]>([]);
  readonly toasts = this._toasts.asReadonly();
  private seq = 0;

  success(message: string): void { this.push('success', message); }
  error(message: string): void { this.push('error', message); }
  info(message: string): void { this.push('info', message); }

  dismiss(id: number): void {
    this._toasts.update((list) => list.filter((t) => t.id !== id));
  }

  private push(kind: ToastKind, message: string): void {
    const id = ++this.seq;
    this._toasts.update((list) => [...list, { id, kind, message }]);
    if (typeof window !== 'undefined') {
      setTimeout(() => this.dismiss(id), AUTO_DISMISS_MS);
    }
  }
}
