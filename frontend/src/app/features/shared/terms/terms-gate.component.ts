/** Terms re-acceptance gate (M11 §7.8).
 *
 * Mounted once by the ShellComponent (which loads TermsFacade on authed app
 * load). Renders a BLOCKING modal — non-dismissable by backdrop/Escape and
 * with no ✕ — whenever the backend reports `needs_acceptance`. The single
 * "I Accept" action POSTs the acceptance and clears the gate on success.
 */
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslateModule } from '@ngx-translate/core';
import { TermsFacade } from '../../../abstraction/facades/terms.facade';
import { ModalComponent } from '../ui/modal.component';

@Component({
  selector: 'app-terms-gate',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslateModule, ModalComponent],
  template: `
    @if (facade.needsAcceptance()) {
      <app-modal [open]="true" [dismissable]="false" [heading]="'terms.title' | translate">
        <div class="space-y-4">
          <p class="text-sm text-slate-600">{{ 'terms.intro' | translate }}</p>

          @if (facade.terms(); as t) {
            <ul class="space-y-2 text-sm">
              <li>
                <a
                  [href]="t.tos_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-medium text-primary-700 underline hover:text-primary-900">
                  {{ 'terms.tos_link' | translate }} (v{{ t.tos_version }})
                </a>
              </li>
              <li>
                <a
                  [href]="t.privacy_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-medium text-primary-700 underline hover:text-primary-900">
                  {{ 'terms.privacy_link' | translate }} (v{{ t.privacy_version }})
                </a>
              </li>
            </ul>
          }

          @if (facade.error()) {
            <p class="text-sm text-red-700" role="alert">{{ 'terms.error' | translate }}</p>
          }

          <div class="flex justify-end">
            <button
              type="button"
              (click)="accept()"
              [disabled]="facade.accepting()"
              class="rounded-md bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 disabled:opacity-50">
              {{ (facade.accepting() ? 'terms.accepting' : 'terms.accept') | translate }}
            </button>
          </div>
        </div>
      </app-modal>
    }
  `,
})
export class TermsGateComponent {
  readonly facade = inject(TermsFacade);

  async accept(): Promise<void> {
    await this.facade.accept();
  }
}
