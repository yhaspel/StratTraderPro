/** /strategies/upload — 3-step upload wizard per AC-03-3, AC-03-4, AC-03-5.
 *
 * Steps:
 *   1. Select files       — three file inputs with live filename validation.
 *   2. Review             — preview parsed description + pine length.
 *   3. Acknowledge & submit — mandatory accept-untested-risk checkbox.
 *
 * Stays as a single component to keep the bundle small. Errors map to the
 * backend's STRATEGY_FILE_* error codes, which are localized client-side.
 *
 * Visual layer: "Industry" design system — shared page header, blueprint
 * card, square step indicator (active accent / done accent-700 / bars
 * bg-accent on a bg-surface track), shared buttons, warn/down tint notices.
 */
import { Component, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { StrategiesFacade } from '../../../abstraction/facades/strategies.facade';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';

const STEM_REGEX = /^[A-Za-z0-9_\-]{3,64}$/;
const MAX_PINE = 64 * 1024;
const MAX_DESC = 16 * 1024;
const MAX_WEBHOOK = 16 * 1024;

@Component({
  selector: 'app-strategies-upload',
  standalone: true,
  imports: [
    CommonModule, FormsModule, TranslateModule,
    ButtonComponent, CardComponent, PageHeaderComponent,
  ],
  template: `
    <div class="mx-auto max-w-2xl p-6">
      <app-page-header
        [heading]="'strategies.upload.title' | translate"
        [subtitle]="'strategies.upload.subtitle' | translate" />

      @if (errorBanner(); as e) {
        <div class="mb-4 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
          {{ e }}
        </div>
      }

      <app-card>
      <!-- Step indicator -->
      <ol class="mb-6 flex items-center text-xs">
        @for (s of [1, 2, 3]; track s) {
          <li class="flex items-center">
            <span [class.bg-accent-700]="step() === s" [class.bg-accent-900]="step() > s" [class.text-bg]="step() >= s"
                  [class.bg-surface]="step() < s" [class.text-neutral-700]="step() < s"
                  class="flex h-6 w-6 items-center justify-center rounded-none font-heading font-semibold">
              {{ s }}
            </span>
            @if (s < 3) {
              <span class="mx-1 h-0.5 w-12" [class.bg-accent]="step() > s" [class.bg-surface]="step() <= s"></span>
            }
          </li>
        }
      </ol>

      <!-- Step 1 — file selection -->
      @if (step() === 1) {
        <div class="space-y-4">
          <div>
            <label for="pine" class="block text-sm font-medium mb-1">{{ 'strategies.upload.pine.label' | translate }}</label>
            <input id="pine" type="file" accept=".pine" (change)="onPineSelected($event)"
                   class="block w-full text-sm" />
            <p class="mt-1 text-xs text-neutral-700">{{ 'strategies.upload.pine.hint' | translate }}</p>
            @if (pineFile()) {
              <p class="mt-1 text-xs" [class.text-down]="pineWarning()" [class.text-warn-deep]="pineSizeWarning() && !pineWarning()">
                {{ pineFile()!.name }} ({{ formatBytes(pineFile()!.size) }})
                @if (pineWarning()) { — {{ pineWarning() }} }
              </p>
            }
          </div>

          <div>
            <label for="description" class="block text-sm font-medium mb-1">{{ 'strategies.upload.desc.label' | translate }}</label>
            <input id="description" type="file" accept=".txt" (change)="onDescSelected($event)"
                   class="block w-full text-sm" />
            <p class="mt-1 text-xs text-neutral-700">{{ 'strategies.upload.desc.hint' | translate : { stem: stem() || '&lt;stem&gt;' } }}</p>
            @if (descFile()) {
              <p class="mt-1 text-xs" [class.text-down]="descWarning()">
                {{ descFile()!.name }} ({{ formatBytes(descFile()!.size) }})
                @if (descWarning()) { — {{ descWarning() }} }
              </p>
            }
          </div>

          <div>
            <label for="webhook" class="block text-sm font-medium mb-1">{{ 'strategies.upload.webhook.label' | translate }}</label>
            <input id="webhook" type="file" accept=".json" (change)="onWebhookSelected($event)"
                   class="block w-full text-sm" />
            <p class="mt-1 text-xs text-neutral-700">{{ 'strategies.upload.webhook.hint' | translate : { stem: stem() || '&lt;stem&gt;' } }}</p>
            @if (webhookFile()) {
              <p class="mt-1 text-xs" [class.text-down]="webhookWarning()">
                {{ webhookFile()!.name }} ({{ formatBytes(webhookFile()!.size) }})
                @if (webhookWarning()) { — {{ webhookWarning() }} }
              </p>
            }
          </div>

          <div class="flex justify-end">
            <app-button variant="primary" [disabled]="!canAdvanceFromStep1()" (clicked)="step.set(2)">
              {{ 'strategies.upload.next' | translate }}
            </app-button>
          </div>
        </div>
      }

      <!-- Step 2 — review -->
      @if (step() === 2) {
        <div class="space-y-4">
          <div>
            <p class="text-sm font-medium mb-1">{{ 'strategies.upload.review.stem' | translate }}</p>
            <p class="font-mono text-sm">{{ stem() }}</p>
          </div>
          <div>
            <p class="text-sm font-medium mb-1">{{ 'strategies.upload.review.pine_size' | translate }}</p>
            <p class="text-sm">{{ formatBytes(pineFile()?.size ?? 0) }}</p>
          </div>
          <div>
            <p class="text-sm font-medium mb-1">{{ 'strategies.upload.review.description_preview' | translate }}</p>
            <pre class="max-h-48 overflow-auto whitespace-pre-wrap rounded-none border border-divider bg-surface p-2 font-mono text-xs text-ink">{{ descPreview() }}</pre>
          </div>
          <div>
            <p class="text-sm font-medium mb-1">{{ 'strategies.upload.review.webhook_keys' | translate }}</p>
            <p class="font-mono text-xs">{{ webhookKeys() }}</p>
          </div>
          <div class="flex justify-between">
            <app-button variant="ghost" (clicked)="step.set(1)">
              ← {{ 'strategies.upload.back' | translate }}
            </app-button>
            <app-button variant="primary" (clicked)="step.set(3)">
              {{ 'strategies.upload.next' | translate }}
            </app-button>
          </div>
        </div>
      }

      <!-- Step 3 — acknowledge & submit -->
      @if (step() === 3) {
        <div class="space-y-4">
          <div class="rounded-none border border-warn bg-warn-tint px-4 py-3 text-sm text-warn-deep">
            <p class="mb-1 font-semibold">⚠ {{ 'strategies.upload.warning.title' | translate }}</p>
            <p>{{ 'strategies.upload.warning.body' | translate }}</p>
          </div>

          <label class="flex items-start gap-2 text-sm">
            <input type="checkbox" [(ngModel)]="acceptRisk" name="acceptRisk" class="mt-1" />
            <span>{{ 'strategies.upload.acknowledge.label' | translate }}</span>
          </label>

          <div class="flex justify-between">
            <app-button variant="ghost" (clicked)="step.set(2)">
              ← {{ 'strategies.upload.back' | translate }}
            </app-button>
            <app-button variant="primary" [disabled]="!acceptRisk" [loading]="submitting()" (clicked)="onSubmit()">
              {{ (submitting() ? 'strategies.upload.submitting' : 'strategies.upload.submit') | translate }}
            </app-button>
          </div>
        </div>
      }
      </app-card>
    </div>
  `,
})
export class StrategiesUploadComponent {
  private facade = inject(StrategiesFacade);
  private router = inject(Router);
  private translate = inject(TranslateService);

  /** P2-DESIGN-8 — humanize byte counts instead of leaking raw "65536 bytes". */
  private humanBytes(n: number): string {
    return n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} bytes`;
  }
  private tooLarge(max: number): string {
    return this.translate.instant('strategies.upload.warn.too_large', { size: this.humanBytes(max) });
  }

  step = signal<1 | 2 | 3>(1);
  pineFile = signal<File | null>(null);
  descFile = signal<File | null>(null);
  webhookFile = signal<File | null>(null);
  acceptRisk = false;
  submitting = signal(false);
  errorBanner = signal<string | null>(null);

  descPreview = signal<string>('');
  webhookKeys = signal<string>('');

  // Stem derived from the .pine filename (sans extension).
  stem = computed(() => {
    const f = this.pineFile();
    if (!f) { return ''; }
    if (!f.name.endsWith('.pine')) { return ''; }
    return f.name.slice(0, -'.pine'.length);
  });

  // Validation messages (rendered in the --down semantic color).
  pineWarning = computed<string | null>(() => {
    const f = this.pineFile();
    if (!f) { return null; }
    if (!f.name.endsWith('.pine')) { return this.translate.instant('strategies.upload.warn.pine_ext'); }
    if (!STEM_REGEX.test(this.stem())) { return this.translate.instant('strategies.upload.warn.stem'); }
    if (f.size > MAX_PINE) { return this.tooLarge(MAX_PINE); }
    return null;
  });
  pineSizeWarning = computed(() => (this.pineFile()?.size ?? 0) > MAX_PINE * 0.8);

  descWarning = computed<string | null>(() => {
    const f = this.descFile();
    if (!f) { return null; }
    const expected = `${this.stem()}_Description.txt`;
    if (this.stem() && f.name !== expected) {
      return this.translate.instant('strategies.upload.warn.filename', { name: expected });
    }
    if (f.size > MAX_DESC) { return this.tooLarge(MAX_DESC); }
    return null;
  });

  webhookWarning = computed<string | null>(() => {
    const f = this.webhookFile();
    if (!f) { return null; }
    const expected = `${this.stem()}_Webhook.json`;
    if (this.stem() && f.name !== expected) {
      return this.translate.instant('strategies.upload.warn.filename', { name: expected });
    }
    if (f.size > MAX_WEBHOOK) { return this.tooLarge(MAX_WEBHOOK); }
    return null;
  });

  canAdvanceFromStep1 = computed(() =>
    !!this.pineFile() && !!this.descFile() && !!this.webhookFile()
    && !this.pineWarning() && !this.descWarning() && !this.webhookWarning()
  );

  onPineSelected(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0] ?? null;
    this.pineFile.set(f);
  }

  async onDescSelected(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0] ?? null;
    this.descFile.set(f);
    if (f) {
      this.descPreview.set((await f.text()).slice(0, 800));
    }
  }

  async onWebhookSelected(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0] ?? null;
    this.webhookFile.set(f);
    if (f) {
      try {
        const obj = JSON.parse(await f.text());
        this.webhookKeys.set(Object.keys(obj as object).join(', '));
      } catch {
        this.webhookKeys.set('(invalid JSON)');
      }
    }
  }

  async onSubmit() {
    if (!this.canAdvanceFromStep1() || !this.acceptRisk) { return; }
    this.submitting.set(true);
    this.errorBanner.set(null);
    const result = await this.facade.upload({
      pine: this.pineFile()!,
      description: this.descFile()!,
      webhook: this.webhookFile()!,
      acceptUntestedRisk: true,
    });
    this.submitting.set(false);
    if (result.ok) {
      this.router.navigate(['/strategies']);
    } else {
      this.errorBanner.set(result.error.message);
    }
  }

  formatBytes(n: number): string {
    if (n < 1024) { return `${n} B`; }
    if (n < 1024 * 1024) { return `${(n / 1024).toFixed(1)} KB`; }
    return `${(n / 1024 / 1024).toFixed(2)} MB`;
  }
}
