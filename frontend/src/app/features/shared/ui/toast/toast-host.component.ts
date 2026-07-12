/** Toast host (M10.5 §7.4) — rendered once in the ShellComponent. */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ToastService } from './toast.service';

@Component({
  selector: 'app-toast-host',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="pointer-events-none fixed inset-x-0 top-4 z-[60] flex flex-col items-center gap-sm px-4">
      @for (t of toast.toasts(); track t.id) {
        <div
          class="pointer-events-auto flex w-full max-w-md items-start gap-md rounded-md px-4 py-3 text-sm shadow-md"
          [class.bg-danger-500]="t.kind === 'error'"
          [class.bg-success-500]="t.kind === 'success'"
          [class.text-white]="t.kind === 'error' || t.kind === 'success'"
          [class.bg-white]="t.kind === 'info'"
          [class.border]="t.kind === 'info'"
          [class.border-slate-200]="t.kind === 'info'"
          [class.text-slate-800]="t.kind === 'info'"
          [attr.role]="t.kind === 'error' ? 'alert' : 'status'"
          [attr.aria-live]="t.kind === 'error' ? 'assertive' : 'polite'">
          <span class="flex-1">{{ t.message }}</span>
          <button
            type="button"
            class="opacity-70 hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
            aria-label="Dismiss"
            (click)="toast.dismiss(t.id)">✕</button>
        </div>
      }
    </div>
  `,
})
export class ToastHostComponent {
  readonly toast = inject(ToastService);
}
