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
          <p class="text-sm text-neutral-700">{{ 'terms.intro' | translate }}</p>

          @if (facade.terms(); as t) {
            <ul class="space-y-2 text-sm">
              <li>
                <a
                  [href]="t.tos_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-medium text-accent-700 underline hover:text-accent-900">
                  {{ 'terms.tos_link' | translate }} (v{{ t.tos_version }})
                </a>
              </li>
              <li>
                <a
                  [href]="t.privacy_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-medium text-accent-700 underline hover:text-accent-900">
                  {{ 'terms.privacy_link' | translate }} (v{{ t.privacy_version }})
                </a>
              </li>
            </ul>
          }

          @if (facade.error()) {
            <p class="text-sm text-down-deep" role="alert">{{ 'terms.error' | translate }}</p>
          }

          <div class="flex justify-end">
            <button
              type="button"
              (click)="accept()"
              [disabled]="facade.accepting()"
              class="rounded-none border border-accent bg-accent px-3 py-1.5 font-heading text-sm font-semibold leading-tight text-bg hover:bg-accent-600 active:bg-accent-700 disabled:cursor-not-allowed disabled:opacity-45">
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
