/** /strategies/upload — 3-step upload wizard per AC-03-3, AC-03-4, AC-03-5.
 *
 * Steps:
 *   1. Select files       — three file inputs with live filename validation.
 *   2. Review             — preview parsed description + pine length.
 *   3. Acknowledge & submit — mandatory accept-untested-risk checkbox.
 *
 * Stays as a single component to keep the bundle small. Errors map to the
 * backend's STRATEGY_FILE_* error codes, which are localized client-side.
 */
import { Component, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { StrategiesFacade } from '../../../abstraction/facades/strategies.facade';

const STEM_REGEX = /^[A-Za-z0-9_\-]{3,64}$/;
const MAX_PINE = 64 * 1024;
const MAX_DESC = 16 * 1024;
const MAX_WEBHOOK = 16 * 1024;

@Component({
  selector: 'app-strategies-upload',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, TranslateModule],
  template: `
    <div class="mx-auto max-w-2xl p-6">
      <h1 class="text-2xl font-bold mb-2">{{ 'strategies.upload.title' | translate }}</h1>
      <p class="text-sm text-gray-600 mb-6">{{ 'strategies.upload.subtitle' | translate }}</p>

      <!-- Step indicator -->
      <ol class="flex items-center mb-6 text-xs">
        @for (s of [1, 2, 3]; track s) {
          <li class="flex items-center">
            <span [class.bg-blue-600]="step() >= s" [class.text-white]="step() >= s"
                  [class.bg-gray-200]="step() < s" class="w-6 h-6 rounded-full flex items-center justify-center font-semibold">
              {{ s }}
            </span>
            @if (s < 3) {
              <span class="w-12 h-0.5 mx-1" [class.bg-blue-600]="step() > s" [class.bg-gray-200]="step() <= s"></span>
            }
          </li>
        }
      </ol>

      @if (errorBanner(); as e) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ e }}
        </div>
      }

      <!-- Step 1 — file selection -->
      @if (step() === 1) {
        <div class="space-y-4">
          <div>
            <label for="pine" class="block text-sm font-medium mb-1">{{ 'strategies.upload.pine.label' | translate }}</label>
            <input id="pine" type="file" accept=".pine" (change)="onPineSelected($event)"
                   class="block w-full text-sm" />
            <p class="text-xs text-gray-500 mt-1">{{ 'strategies.upload.pine.hint' | translate }}</p>
            @if (pineFile()) {
              <p class="text-xs mt-1" [class.text-red-700]="pineWarning()" [class.text-amber-700]="pineSizeWarning() && !pineWarning()">
                {{ pineFile()!.name }} ({{ formatBytes(pineFile()!.size) }})
                @if (pineWarning()) { — {{ pineWarning() }} }
              </p>
            }
          </div>

          <div>
            <label for="description" class="block text-sm font-medium mb-1">{{ 'strategies.upload.desc.label' | translate }}</label>
            <input id="description" type="file" accept=".txt" (change)="onDescSelected($event)"
                   class="block w-full text-sm" />
            <p class="text-xs text-gray-500 mt-1">{{ 'strategies.upload.desc.hint' | translate : { stem: stem() || '<stem>' } }}</p>
            @if (descFile()) {
              <p class="text-xs mt-1" [class.text-red-700]="descWarning()">
                {{ descFile()!.name }} ({{ formatBytes(descFile()!.size) }})
                @if (descWarning()) { — {{ descWarning() }} }
              </p>
            }
          </div>

          <div>
            <label for="webhook" class="block text-sm font-medium mb-1">{{ 'strategies.upload.webhook.label' | translate }}</label>
            <input id="webhook" type="file" accept=".json" (change)="onWebhookSelected($event)"
                   class="block w-full text-sm" />
            <p class="text-xs text-gray-500 mt-1">{{ 'strategies.upload.webhook.hint' | translate : { stem: stem() || '<stem>' } }}</p>
            @if (webhookFile()) {
              <p class="text-xs mt-1" [class.text-red-700]="webhookWarning()">
                {{ webhookFile()!.name }} ({{ formatBytes(webhookFile()!.size) }})
                @if (webhookWarning()) { — {{ webhookWarning() }} }
              </p>
            }
          </div>

          <div class="flex justify-end">
            <button type="button" (click)="step.set(2)" [disabled]="!canAdvanceFromStep1()"
                    class="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-sm px-4 py-2 rounded">
              {{ 'strategies.upload.next' | translate }}
            </button>
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
            <pre class="bg-gray-50 border rounded p-2 text-xs whitespace-pre-wrap max-h-48 overflow-auto">{{ descPreview() }}</pre>
          </div>
          <div>
            <p class="text-sm font-medium mb-1">{{ 'strategies.upload.review.webhook_keys' | translate }}</p>
            <p class="font-mono text-xs">{{ webhookKeys() }}</p>
          </div>
          <div class="flex justify-between">
            <button type="button" (click)="step.set(1)"
                    class="text-sm text-gray-700 hover:underline">
              ← {{ 'strategies.upload.back' | translate }}
            </button>
            <button type="button" (click)="step.set(3)"
                    class="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded">
              {{ 'strategies.upload.next' | translate }}
            </button>
          </div>
        </div>
      }

      <!-- Step 3 — acknowledge & submit -->
      @if (step() === 3) {
        <div class="space-y-4">
          <div class="bg-amber-50 border border-amber-300 text-amber-900 px-4 py-3 rounded text-sm">
            <p class="font-semibold mb-1">⚠ {{ 'strategies.upload.warning.title' | translate }}</p>
            <p>{{ 'strategies.upload.warning.body' | translate }}</p>
          </div>

          <label class="flex items-start gap-2 text-sm">
            <input type="checkbox" [(ngModel)]="acceptRisk" name="acceptRisk" class="mt-1" />
            <span>{{ 'strategies.upload.acknowledge.label' | translate }}</span>
          </label>

          <div class="flex justify-between">
            <button type="button" (click)="step.set(2)"
                    class="text-sm text-gray-700 hover:underline">
              ← {{ 'strategies.upload.back' | translate }}
            </button>
            <button type="button" (click)="onSubmit()"
                    [disabled]="!acceptRisk || submitting()"
                    class="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white text-sm px-4 py-2 rounded">
              {{ (submitting() ? 'strategies.upload.submitting' : 'strategies.upload.submit') | translate }}
            </button>
          </div>
        </div>
      }
    </div>
  `,
})
export class StrategiesUploadComponent {
  private facade = inject(StrategiesFacade);
  private router = inject(Router);

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

  // Validation messages (rendered red).
  pineWarning = computed<string | null>(() => {
    const f = this.pineFile();
    if (!f) { return null; }
    if (!f.name.endsWith('.pine')) { return 'Must end in .pine'; }
    if (!STEM_REGEX.test(this.stem())) { return 'Stem must be 3–64 chars [A-Za-z0-9_-]'; }
    if (f.size > MAX_PINE) { return `File exceeds ${MAX_PINE} bytes`; }
    return null;
  });
  pineSizeWarning = computed(() => (this.pineFile()?.size ?? 0) > MAX_PINE * 0.8);

  descWarning = computed<string | null>(() => {
    const f = this.descFile();
    if (!f) { return null; }
    const expected = `${this.stem()}_Description.txt`;
    if (this.stem() && f.name !== expected) { return `Filename must be ${expected}`; }
    if (f.size > MAX_DESC) { return `File exceeds ${MAX_DESC} bytes`; }
    return null;
  });

  webhookWarning = computed<string | null>(() => {
    const f = this.webhookFile();
    if (!f) { return null; }
    const expected = `${this.stem()}_Webhook.json`;
    if (this.stem() && f.name !== expected) { return `Filename must be ${expected}`; }
    if (f.size > MAX_WEBHOOK) { return `File exceeds ${MAX_WEBHOOK} bytes`; }
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
