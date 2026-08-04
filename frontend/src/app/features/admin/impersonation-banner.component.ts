/** Persistent banner shown while an admin impersonation session is active.
 *
 * The active session lives in AdminStore; this banner reads it via the facade
 * and renders a Stop button that calls `stopImpersonation()`. Rendered at the
 * top of every admin page so the operator can't lose track of the session.
 *
 * Industry styling: full-width WARN banner (warn tint ground + warn-deep text,
 * condensed uppercase per the halt-banner grammar) — deliberately distinct from
 * the solid down-red platform-halt banner.
 */
import { Component, computed, inject, signal } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ToastService } from '../shared/ui/toast/toast.service';
import { ButtonComponent } from '../shared/ui/button.component';

@Component({
  selector: 'app-impersonation-banner',
  standalone: true,
  imports: [TranslateModule, ButtonComponent],
  template: `
    @if (admin.impersonation(); as session) {
      <div class="flex w-full items-center justify-center gap-s3 bg-warn-tint px-s4 py-s2 font-heading text-sm font-semibold uppercase tracking-wide text-warn-deep"
           role="status">
        <span>
          ⚠ {{ 'admin.impersonation.banner' | translate }}
          @if (impersonatedLabel(); as who) {
            <span class="font-mono normal-case tracking-normal">— {{ who }}</span>
          }
        </span>
        <app-button variant="secondary" [disabled]="stopping()" (clicked)="stop()">
          {{ (stopping() ? 'admin.impersonation.stopping' : 'admin.impersonation.stop') | translate }}
        </app-button>
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
