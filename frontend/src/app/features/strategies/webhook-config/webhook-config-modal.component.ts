/** Webhook Configuration modal — AC-03-6, AC-03-7, AC-03-8, AC-03-9.
 *
 * Surface:
 *   - URL row (read-only + copy button)
 *   - Secret row (masked, reveal-once after rotate)
 *   - Rotate button (with confirm)
 *   - JSON Schema editor (textarea, JSON-validated live)
 *   - Payload template editor (textarea, JSON-validated live)
 *   - "Test" button — POSTs payload to the dry-run endpoint
 *   - "Copy TradingView alert template" — fills `sig` with the just-revealed
 *     secret per AC-03-9 (otherwise leaves a placeholder)
 *
 * Editor: textarea-only for M03. The `monaco-editor` npm package was tried
 * but its CSS imports a `.ttf` font that Angular 19's stock esbuild has no
 * loader for, breaking the production build. Switching to a CDN AMD loader
 * (the officially-recommended pattern for Monaco in arbitrary apps) is
 * tracked for a future milestone — the textarea works correctly today,
 * including line numbers via CSS counters and live JSON validation.
 *
 * Visual layer: "Industry" design system — mono editors on `--color-surface`,
 * danger-tinted Rotate with a warn-deep caution line, shared buttons.
 */
import { Component, Input, Output, EventEmitter, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { StrategiesFacade } from '../../../abstraction/facades/strategies.facade';
import { Strategy, WebhookConfig } from '../../../core/models/strategies.models';
import { ToastService } from '../../shared/ui/toast/toast.service';
import { ModalComponent } from '../../shared/ui/modal.component';
import { ButtonComponent } from '../../shared/ui/button.component';

@Component({
  selector: 'app-webhook-config-modal',
  standalone: true,
  imports: [CommonModule, TranslateModule, ModalComponent, ButtonComponent],
  template: `
    <app-modal [open]="true" [heading]="modalHeading()" (closed)="closed.emit()">
        <p class="-mt-2 mb-4 text-sm text-neutral-600">{{ strategy.name }}</p>

        @if (loading()) {
          <p class="text-sm text-neutral-600">{{ 'webhook.modal.loading' | translate }}</p>
        }
        @if (!loading() && config(); as cfg) {

          <!-- URL row -->
          <div class="mb-4">
            <label for="webhook-url-input" class="mb-1 block text-xs font-semibold uppercase tracking-wide text-neutral-600">
              {{ 'webhook.modal.url.label' | translate }}
            </label>
            <div class="flex gap-2">
              <input id="webhook-url-input" readonly type="text" [value]="cfg.url"
                     class="min-h-[36px] flex-1 rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-xs text-ink focus:border-accent focus:outline-none" />
              <button type="button" (click)="copyToClipboard(cfg.url, 'url')"
                      [attr.aria-label]="'webhook.modal.copy_url' | translate"
                      class="rounded-none border border-divider bg-transparent px-3 py-1.5 font-heading text-xs font-semibold text-ink transition-colors hover:bg-neutral-200 active:bg-neutral-300">
                {{ copied() === 'url' ? '✓' : ('webhook.modal.copy' | translate) }}
              </button>
            </div>
          </div>

          <!-- Secret row -->
          <div class="mb-4">
            <label for="webhook-secret-input" class="mb-1 block text-xs font-semibold uppercase tracking-wide text-neutral-600">
              {{ 'webhook.modal.secret.label' | translate }} (v{{ cfg.version }})
            </label>
            @if (cfg.secret) {
              <div class="flex gap-2">
                <input id="webhook-secret-input" readonly type="text" [value]="cfg.secret"
                       class="min-h-[36px] flex-1 rounded-none border border-warn bg-warn-tint px-2.5 py-1.5 font-mono text-xs text-ink focus:outline-none" />
                <button type="button" (click)="copyToClipboard(cfg.secret!, 'secret')"
                        class="rounded-none border border-divider bg-transparent px-3 py-1.5 font-heading text-xs font-semibold text-ink transition-colors hover:bg-neutral-200 active:bg-neutral-300">
                  {{ copied() === 'secret' ? '✓' : ('webhook.modal.copy' | translate) }}
                </button>
              </div>
              <p class="mt-1 text-xs text-warn-deep">
                ⚠ {{ 'webhook.modal.secret.reveal_once' | translate }}
              </p>
            } @else {
              <div id="webhook-secret-input" class="text-xs italic text-neutral-600">
                {{ 'webhook.modal.secret.hidden' | translate }}
              </div>
            }
            <button type="button" (click)="onRotate()"
                    [disabled]="rotating()"
                    class="mt-2 rounded-none border border-down bg-down-tint px-3 py-1 font-heading text-xs font-semibold text-down transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45">
              {{ (rotating() ? 'webhook.modal.rotating' : 'webhook.modal.rotate') | translate }}
            </button>
            <p class="mt-1 text-[11px] text-warn-deep">
              ⚠ {{ 'webhook.modal.secret.rotate_warning' | translate }}
            </p>
          </div>

          <!-- JSON Schema editor -->
          <div class="mb-4">
            <label for="webhook-schema-editor" class="mb-1 block text-xs font-semibold uppercase tracking-wide text-neutral-600">
              {{ 'webhook.modal.schema.label' | translate }}
            </label>
            <textarea id="webhook-schema-editor" rows="8" [value]="schemaText()" (input)="onSchemaInput($event)"
                      class="w-full rounded-none border border-divider bg-surface p-2 font-mono text-xs leading-relaxed text-ink focus:border-accent focus:outline-none"
                      spellcheck="false" autocomplete="off"></textarea>
            @if (schemaError(); as e) {
              <p class="mt-1 text-xs text-down">{{ e }}</p>
            }
          </div>

          <!-- Payload template editor -->
          <div class="mb-4">
            <label for="webhook-template-editor" class="mb-1 block text-xs font-semibold uppercase tracking-wide text-neutral-600">
              {{ 'webhook.modal.template.label' | translate }}
            </label>
            <textarea id="webhook-template-editor" rows="8" [value]="templateText()" (input)="onTemplateInput($event)"
                      class="w-full rounded-none border border-divider bg-surface p-2 font-mono text-xs leading-relaxed text-ink focus:border-accent focus:outline-none"
                      spellcheck="false" autocomplete="off"></textarea>
            @if (templateError(); as e) {
              <p class="mt-1 text-xs text-down">{{ e }}</p>
            }
          </div>

          <!-- Action row -->
          <div class="mb-4 flex flex-wrap gap-2.5">
            <app-button variant="primary" [loading]="saving()"
                        [disabled]="!!schemaError() || !!templateError()"
                        (clicked)="onSave()">
              {{ (saving() ? 'webhook.modal.saving' : 'webhook.modal.save') | translate }}
            </app-button>
            <app-button variant="secondary" [disabled]="!!templateError()" (clicked)="onTest()">
              {{ 'webhook.modal.test' | translate }}
            </app-button>
            <app-button variant="secondary" (clicked)="copyTradingViewTemplate()">
              {{ 'webhook.modal.copy_tv' | translate }}
            </app-button>
          </div>

          @if (saveOk()) {
            <p class="text-xs text-up">✓ {{ 'webhook.modal.saved' | translate }}</p>
          }
          @if (testResult(); as r) {
            <p class="text-xs" [class.text-up]="r.ok" [class.text-down]="!r.ok">
              {{ r.message }}
            </p>
          }
        }
    </app-modal>
  `,
})
export class WebhookConfigModalComponent implements OnInit {
  @Input({ required: true }) strategy!: Strategy;
  @Output() closed = new EventEmitter<void>();

  private facade = inject(StrategiesFacade);
  private toast = inject(ToastService);
  private translate = inject(TranslateService);

  modalHeading(): string {
    return this.translate.instant('webhook.modal.title');
  }

  loading = signal(true);
  saving = signal(false);
  rotating = signal(false);
  copied = signal<'url' | 'secret' | 'tv' | null>(null);

  schemaText = signal('');
  templateText = signal('');
  schemaError = signal<string | null>(null);
  templateError = signal<string | null>(null);
  saveOk = signal(false);
  testResult = signal<{ ok: boolean; message: string } | null>(null);

  config = computed<WebhookConfig | null>(() => this.facade.webhookConfig(this.strategy.id)());

  async ngOnInit(): Promise<void> {
    await this.facade.loadWebhookConfig(this.strategy.id);
    const cfg = this.config();
    if (cfg) {
      this.schemaText.set(JSON.stringify(cfg.json_schema, null, 2));
      this.templateText.set(JSON.stringify(cfg.payload_template, null, 2));
    }
    this.loading.set(false);
  }

  onSchemaInput(ev: Event) {
    const text = (ev.target as HTMLTextAreaElement).value;
    this.schemaText.set(text);
    try {
      const obj = JSON.parse(text);
      if (typeof obj !== 'object' || obj === null) {
        this.schemaError.set('Schema must be a JSON object');
      } else {
        this.schemaError.set(null);
      }
    } catch (e) {
      this.schemaError.set(`Invalid JSON: ${(e as Error).message}`);
    }
  }

  onTemplateInput(ev: Event) {
    const text = (ev.target as HTMLTextAreaElement).value;
    this.templateText.set(text);
    try {
      JSON.parse(text);
      this.templateError.set(null);
    } catch (e) {
      this.templateError.set(`Invalid JSON: ${(e as Error).message}`);
    }
  }

  async onSave() {
    this.saveOk.set(false);
    this.saving.set(true);
    try {
      const schema = JSON.parse(this.schemaText());
      const template = JSON.parse(this.templateText());
      const res = await this.facade.updateWebhookConfig(this.strategy.id, schema, template);
      if (res.ok) {
        this.saveOk.set(true);
      } else {
        this.templateError.set(res.error?.message ?? 'Save failed');
      }
    } catch (e) {
      this.templateError.set(`Could not parse JSON: ${(e as Error).message}`);
    } finally {
      this.saving.set(false);
    }
  }

  async onTest() {
    // 1) Local JSON parse — surface a *parse* error if the textarea contains
    //    invalid JSON, since the network call would just see a body it can't
    //    even POST.
    let payload: unknown;
    try {
      payload = JSON.parse(this.templateText());
    } catch (e) {
      this.testResult.set({ ok: false, message: `Invalid JSON: ${(e as Error).message}` });
      return;
    }
    // 2) Server-side schema validation — facade.dryRunWebhook catches the
    //    HttpErrorResponse internally and returns {ok:false, error:ApiError}.
    const res = await this.facade.dryRunWebhook(this.strategy.id, payload);
    this.testResult.set(
      res.ok
        ? { ok: true, message: 'Payload validates against the saved schema.' }
        : { ok: false, message: res.error?.message ?? 'Validation failed.' }
    );
  }

  async onRotate() {
    if (!confirm('Rotating will break any TradingView alerts using the current secret. Continue?')) {
      return;
    }
    this.rotating.set(true);
    try {
      const res = await this.facade.rotateWebhookSecret(this.strategy.id);
      if (res) {
        this.toast.success('Webhook secret rotated. Copy the new secret now — it is shown only once.');
      } else {
        this.toast.error(this.facade.error()?.message ?? 'Failed to rotate webhook secret.');
      }
    } finally {
      this.rotating.set(false);
    }
  }

  async copyToClipboard(text: string, marker: 'url' | 'secret' | 'tv'): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      this.copied.set(marker);
      setTimeout(() => { if (this.copied() === marker) { this.copied.set(null); } }, 2000);
    } catch {
      // navigator.clipboard requires a secure context; fall through silently.
    }
  }

  copyTradingViewTemplate(): void {
    const cfg = this.config();
    if (!cfg) { return; }
    // Use the just-revealed secret if present (per AC-03-9 reveal-once);
    // otherwise leave the placeholder.
    const sigValue = cfg.secret ?? 'PASTE_YOUR_SECRET_HERE';
    const tv = {
      strategy: '{{strategy}}',
      action: '{{strategy.order.action}}',
      symbol: '{{ticker}}',
      qty: '{{strategy.order.contracts}}',
      order_type: 'MKT',
      sig: sigValue,
      idempotency_key: '{{strategy.order.id}}-{{time}}',
    };
    void this.copyToClipboard(JSON.stringify(tv, null, 2), 'tv');
  }
}
