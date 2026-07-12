/** Persistent banner shown while an admin impersonation session is active.
 *
 * The active session lives in AdminStore; this banner reads it via the facade
 * and renders a Stop button that calls `stopImpersonation()`. Rendered at the
 * top of every admin page so the operator can't lose track of the session.
 */
import { Component, computed, inject, signal } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ToastService } from '../shared/ui/toast/toast.service';

@Component({
  selector: 'app-impersonation-banner',
  standalone: true,
  imports: [TranslateModule],
  template: `
    @if (admin.impersonation(); as session) {
      <div class="bg-amber-500 text-black px-4 py-2 text-sm font-semibold flex items-center justify-center gap-4"
           role="alert">
        <span>
          ⚠ {{ 'admin.impersonation.banner' | translate }}
          @if (impersonatedLabel(); as who) {
            <span class="font-mono">— {{ who }}</span>
          }
        </span>
        <button type="button" (click)="stop()" [disabled]="stopping()"
                class="bg-black/80 text-white px-3 py-1 rounded text-xs hover:bg-black disabled:opacity-50">
          {{ (stopping() ? 'admin.impersonation.stopping' : 'admin.impersonation.stop') | translate }}
        </button>
      </div>
    }
  `,
})
export class ImpersonationBannerComponent {
  admin = inject(AdminFacade);
  private toast = inject(ToastService);
  stopping = signal(false);

  /** Who is being impersonated. The session token itself carries no email, so
   * fall back to the selected user (populated when the session was started from
   * the user-detail page) and finally to the session id. */
  impersonatedLabel = computed(() => {
    const user = this.admin.selectedUser();
    if (user) { return user.email; }
    return this.admin.impersonation()?.session_id ?? null;
  });

  async stop(): Promise<void> {
    this.stopping.set(true);
    try {
      const res = await this.admin.stopImpersonation();
      if (!res.ok) {
        this.toast.error(res.error?.message ?? 'Failed to stop impersonation.');
      }
    } finally {
      this.stopping.set(false);
    }
  }
}
