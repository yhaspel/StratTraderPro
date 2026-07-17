/** /strategies — list view per AC-03-2.
 *
 * Columns: name, type (system / user), enabled toggle, webhook status,
 * actions ("Configure webhook", "View", "Delete" for user uploads).
 *
 * The "Configure webhook" action lazy-loads the WebhookConfigModal from
 * the same chunk as Monaco editor (see modal component for the dynamic
 * import).
 */
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { StrategiesFacade } from '../../../abstraction/facades/strategies.facade';
import { Strategy } from '../../../core/models/strategies.models';
import { WebhookConfigModalComponent } from '../webhook-config/webhook-config-modal.component';
import { ModalComponent } from '../../shared/ui/modal.component';

@Component({
  selector: 'app-strategies-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, TranslateModule, WebhookConfigModalComponent, ModalComponent],
  template: `
    <div class="mx-auto max-w-6xl p-6">
      <div class="flex items-center justify-between mb-6">
        <h1 class="text-2xl font-bold">{{ 'strategies.list.title' | translate }}</h1>
        <a routerLink="/strategies/upload"
           class="inline-flex items-center bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded">
          {{ 'strategies.list.upload_button' | translate }}
        </a>
      </div>

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ err.message }}
        </div>
      }

      @if (facade.loading()) {
        <p class="text-sm text-gray-500">{{ 'strategies.list.loading' | translate }}</p>
      } @else if (facade.strategies().length === 0) {
        <p class="text-sm text-gray-500">{{ 'strategies.list.empty' | translate }}</p>
      } @else {
        <table class="w-full border border-gray-200 text-sm">
          <thead class="bg-gray-50 text-left">
            <tr>
              <th class="px-3 py-2">{{ 'strategies.list.col.name' | translate }}</th>
              <th class="px-3 py-2">{{ 'strategies.list.col.type' | translate }}</th>
              <th class="px-3 py-2">{{ 'strategies.list.col.enabled' | translate }}</th>
              <th class="px-3 py-2">{{ 'strategies.list.col.webhook' | translate }}</th>
              <th class="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            @for (s of facade.strategies(); track s.id) {
              <tr class="border-t border-gray-100">
                <td class="px-3 py-3">
                  <div class="font-medium">{{ s.name }}</div>
                  <div class="text-xs text-gray-500">{{ s.description_short }}</div>
                  @if (!s.is_system) {
                    <div class="mt-2 inline-block bg-amber-50 border border-amber-200 text-amber-800 text-xs px-2 py-1 rounded">
                      ⚠ {{ 'strategies.list.untested_banner' | translate }}
                    </div>
                  }
                </td>
                <td class="px-3 py-3">
                  @if (s.is_system) {
                    <span class="bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded">
                      {{ 'strategies.list.badge.system' | translate }}
                    </span>
                  } @else {
                    <span class="bg-gray-100 text-gray-800 text-xs px-2 py-1 rounded">
                      {{ 'strategies.list.badge.user' | translate }}
                    </span>
                  }
                </td>
                <td class="px-3 py-3">
                  <button type="button" (click)="onToggle(s)"
                          role="switch"
                          [attr.aria-checked]="s.is_enabled"
                          [attr.aria-label]="(s.is_enabled ? 'strategies.list.disable' : 'strategies.list.enable') | translate"
                          [class.bg-green-500]="s.is_enabled"
                          [class.bg-gray-300]="!s.is_enabled"
                          class="w-12 h-6 rounded-full relative transition-colors">
                    <span class="absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all"
                          [class.left-0.5]="!s.is_enabled" [class.left-6]="s.is_enabled"></span>
                  </button>
                </td>
                <td class="px-3 py-3 text-xs">
                  {{ (s.has_webhook_config ? 'strategies.list.webhook.configured' : 'strategies.list.webhook.unconfigured') | translate }}
                </td>
                <td class="px-3 py-3 text-right space-x-2">
                  <button type="button" (click)="openWebhookModal(s)"
                          class="text-blue-600 hover:underline text-sm">
                    {{ 'strategies.list.configure_webhook' | translate }}
                  </button>
                  @if (!s.is_system) {
                    <button type="button" (click)="onDelete(s)"
                            class="text-red-600 hover:underline text-sm">
                      {{ 'strategies.list.delete' | translate }}
                    </button>
                  }
                </td>
              </tr>
            }
          </tbody>
        </table>
      }
    </div>

    @if (modalStrategy(); as ms) {
      <app-webhook-config-modal
        [strategy]="ms"
        (closed)="closeModal()" />
    }

    <!-- P1-10 — enabling arms live execution; confirm the consequence first. -->
    <app-modal
      [open]="enablingStrategy() !== null"
      [heading]="'strategies.list.enable_confirm.title' | translate"
      (closed)="cancelEnable()">
      <p class="text-sm text-slate-700 mb-4">{{ 'strategies.list.enable_confirm.body' | translate }}</p>
      <div class="flex justify-end gap-2">
        <button type="button" (click)="cancelEnable()"
                class="px-3 py-2 rounded text-sm border hover:bg-gray-50">
          {{ 'common.cancel' | translate }}
        </button>
        <button type="button" (click)="confirmEnable()"
                class="bg-green-600 text-white px-3 py-2 rounded text-sm hover:bg-green-700">
          {{ 'strategies.list.enable_confirm.confirm' | translate }}
        </button>
      </div>
    </app-modal>
  `,
})
export class StrategiesListComponent implements OnInit {
  facade = inject(StrategiesFacade);
  private router = inject(Router);
  private translate = inject(TranslateService);

  /** Strategy currently being configured in the modal, or null. */
  modalStrategy = signal<Strategy | null>(null);
  /** Strategy pending an enable confirmation, or null (P1-10). */
  enablingStrategy = signal<Strategy | null>(null);

  ngOnInit(): void {
    this.facade.load();
  }

  onToggle(s: Strategy): void {
    // Disabling is safe and immediate; enabling arms live order execution, so it
    // requires an explicit confirmation (P1-10).
    if (s.is_enabled) {
      void this.facade.toggleEnabled(s.id, false);
    } else {
      this.enablingStrategy.set(s);
    }
  }

  cancelEnable(): void {
    this.enablingStrategy.set(null);
  }

  async confirmEnable(): Promise<void> {
    const s = this.enablingStrategy();
    if (!s) { return; }
    this.enablingStrategy.set(null);
    await this.facade.toggleEnabled(s.id, true);
  }

  async onDelete(s: Strategy): Promise<void> {
    const msg = this.translate.instant('strategies.list.delete_confirm', { name: s.name });
    if (!confirm(msg)) {
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
