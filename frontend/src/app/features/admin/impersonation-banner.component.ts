/** Persistent banner shown while an admin impersonation session is active.
 *
 * The active session lives in AdminStore; this banner reads it via the facade
 * and renders a Stop button that calls `stopImpersonation()`. Rendered at the
 * top of every admin page so the operator can't lose track of the session.
 */
import { Component, inject, signal } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';

@Component({
  selector: 'app-impersonation-banner',
  standalone: true,
  imports: [TranslateModule],
  template: `
    @if (admin.impersonation(); as session) {
      <div class="bg-amber-500 text-black px-4 py-2 text-sm font-semibold flex items-center justify-center gap-4"
           role="alert">
        <span>⚠ {{ 'admin.impersonation.banner' | translate }}</span>
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
  stopping = signal(false);

  async stop(): Promise<void> {
    this.stopping.set(true);
    try {
      await this.admin.stopImpersonation();
    } finally {
      this.stopping.set(false);
    }
  }
}
