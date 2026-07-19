/** /strategies — list view per AC-03-2.
 *
 * Columns: name, type (system / user), enabled toggle, webhook status,
 * actions ("Configure webhook", "View", "Delete" for user uploads).
 *
 * The "Configure webhook" action lazy-loads the WebhookConfigModal from
 * the same chunk as Monaco editor (see modal component for the dynamic
 * import).
 *
 * Visual layer: "Industry" design system — blueprint-framed table panel,
 * shared status chips (SYSTEM/USER/untested), shared square toggle.
 */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { StrategiesFacade } from '../../../abstraction/facades/strategies.facade';
import { Strategy } from '../../../core/models/strategies.models';
import { WebhookConfigModalComponent } from '../webhook-config/webhook-config-modal.component';
import { BlueprintDirective } from '../../shared/ui/blueprint.directive';
import { ButtonComponent } from '../../shared/ui/button.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { StatusChipComponent } from '../../shared/ui/status-chip.component';
import { ToggleComponent } from '../../shared/ui/toggle.component';

@Component({
  selector: 'app-strategies-list',
  standalone: true,
  imports: [
    CommonModule, RouterLink, TranslateModule, WebhookConfigModalComponent,
    BlueprintDirective, ButtonComponent, PageHeaderComponent, StatusChipComponent, ToggleComponent,
  ],
  template: `
    <div class="mx-auto max-w-6xl p-6">
      <app-page-header [heading]="'strategies.list.title' | translate">
        <a actions routerLink="/strategies/upload" stpBlueprint
           class="inline-flex items-center justify-center rounded-none border border-accent-700 bg-accent-700 px-3 py-1.5 font-heading text-sm font-semibold leading-tight text-bg no-underline transition-colors hover:bg-accent-800 active:bg-accent-900">
          {{ 'strategies.list.upload_button' | translate }}
        </a>
      </app-page-header>

      @if (facade.error(); as err) {
        <div class="mb-4 rounded-none border border-down bg-down-tint px-s4 py-s3 text-sm text-down-deep" role="alert">
          {{ err.message }}
        </div>
      }

      @if (facade.loading()) {
        <p class="text-sm text-neutral-700">{{ 'strategies.list.loading' | translate }}</p>
      } @else if (facade.strategies().length === 0) {
        <p class="text-sm text-neutral-700">{{ 'strategies.list.empty' | translate }}</p>
      } @else {
        <div stpBlueprint class="bg-transparent">
          <table class="w-full text-[13px]">
            <thead class="text-left">
              <tr class="border-b border-divider">
                <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'strategies.list.col.name' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'strategies.list.col.type' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'strategies.list.col.enabled' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'strategies.list.col.webhook' | translate }}</th>
                <th class="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              @for (s of facade.strategies(); track s.id) {
                <tr class="border-t border-neutral-200">
                  <td class="px-3 py-3">
                    <div class="font-bold">{{ s.name }}</div>
                    <div class="mt-0.5 text-xs text-neutral-700">{{ s.description_short }}</div>
                    @if (!s.is_system) {
                      <div class="mt-1.5">
                        <app-status-chip tone="warn">
                          ⚠ {{ 'strategies.list.untested_banner' | translate }}
                        </app-status-chip>
                      </div>
                    }
                  </td>
                  <td class="px-3 py-3">
                    @if (s.is_system) {
                      <app-status-chip status="SYSTEM">
                        {{ 'strategies.list.badge.system' | translate }}
                      </app-status-chip>
                    } @else {
                      <app-status-chip status="USER">
                        {{ 'strategies.list.badge.user' | translate }}
                      </app-status-chip>
                    }
                  </td>
                  <td class="px-3 py-3">
                    <app-toggle
                      [checked]="s.is_enabled"
                      [ariaLabel]="(s.is_enabled ? 'strategies.list.disable' : 'strategies.list.enable') | translate"
                      (toggled)="onToggle(s)" />
                  </td>
                  <td class="px-3 py-3 text-xs text-neutral-700">
                    {{ (s.has_webhook_config ? 'strategies.list.webhook.configured' : 'strategies.list.webhook.unconfigured') | translate }}
                  </td>
                  <td class="whitespace-nowrap px-3 py-3 text-right space-x-2">
                    <app-button variant="ghost" (clicked)="openWebhookModal(s)">
                      {{ 'strategies.list.configure_webhook' | translate }}
                    </app-button>
                    @if (!s.is_system) {
                      <button type="button" (click)="onDelete(s)"
                              class="rounded-none border border-transparent px-1 py-1.5 font-heading text-sm font-semibold leading-tight text-down transition-colors hover:bg-down-tint">
                        {{ 'strategies.list.delete' | translate }}
                      </button>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </div>

    @if (modalStrategy(); as ms) {
      <app-webhook-config-modal
        [strategy]="ms"
        (closed)="closeModal()" />
    }
  `,
})
export class StrategiesListComponent implements OnInit {
  facade = inject(StrategiesFacade);
  private router = inject(Router);

  /** Strategy currently being configured in the modal, or null. */
  modalStrategy = signal<Strategy | null>(null);

  ngOnInit(): void {
    this.facade.load();
  }

  async onToggle(s: Strategy): Promise<void> {
    await this.facade.toggleEnabled(s.id, !s.is_enabled);
  }

  async onDelete(s: Strategy): Promise<void> {
    if (!confirm(`Delete ${s.name}? This is reversible by toggling 'is_enabled' in admin.`)) {
      return;
    }
    await this.facade.softDelete(s.id);
  }

  openWebhookModal(s: Strategy): void {
    this.modalStrategy.set(s);
  }

  closeModal(): void {
    this.modalStrategy.set(null);
    // Wipe any reveal-once secret that might still be in memory.
    const ms = this.facade.strategies();
    for (const s of ms) {
      this.facade.clearRevealedSecret(s.id);
    }
    // Refresh the list so `has_webhook_config` reflects any config the user
    // just created or rotated inside the modal. Fire-and-forget — the table
    // updates in place when the response arrives.
    void this.facade.load();
  }
}
