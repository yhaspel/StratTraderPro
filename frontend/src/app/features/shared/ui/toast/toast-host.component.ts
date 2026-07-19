/** Toast host (M10.5 §7.4) — rendered once in the ShellComponent. */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ToastService } from './toast.service';

@Component({
  selector: 'app-toast-host',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="pointer-events-none fixed inset-x-0 top-4 z-[60] flex flex-col items-center gap-s2 px-4">
      @for (t of toast.toasts(); track t.id) {
        <div
          class="pointer-events-auto flex w-full max-w-md items-start gap-s3 rounded-none border border-divider border-l-[3px] bg-white px-4 py-3 text-sm text-ink shadow-md"
          [class.border-l-down]="t.kind === 'error'"
          [class.border-l-up]="t.kind === 'success'"
          [class.border-l-accent]="t.kind === 'info'"
          [attr.role]="t.kind === 'error' ? 'alert' : 'status'"
          [attr.aria-live]="t.kind === 'error' ? 'assertive' : 'polite'">
          <span class="flex-1">{{ t.message }}</span>
          <button
            type="button"
            class="opacity-70 hover:opacity-100"
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
