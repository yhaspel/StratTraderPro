/**
 * /settings/security/mfa/setup — multi-step enrollment wizard.
 *
 *   1. Intro
 *   2. QR / secret display
 *   3. 6-digit confirm
 *   4. Backup codes (with click-to-confirm + .txt download)
 *   5. Done
 */
import { Component, ViewChild, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { MfaFacade } from '../../../abstraction/facades/mfa.facade';
import { TotpInputComponent } from '../../auth/totp-input/totp-input.component';

type Step = 'intro' | 'qr' | 'verify' | 'backup' | 'done';

@Component({
  selector: 'app-mfa-setup',
  standalone: true,
  imports: [CommonModule, RouterLink, TranslateModule, TotpInputComponent],
  template: `
    <div class="mx-auto max-w-xl p-6">
      <h1 class="text-2xl font-bold mb-6">{{ 'mfa.setup.title' | translate }}</h1>

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ 'mfa.error.' + err.code | translate : { default: err.message } }}
        </div>
      }

      <!-- step indicator -->
      <div class="flex gap-2 mb-6 text-xs uppercase tracking-wide text-gray-500">
        <span [class.font-bold]="step() === 'intro'">1. {{ 'mfa.setup.step.intro' | translate }}</span>
        <span>›</span>
        <span [class.font-bold]="step() === 'qr'">2. {{ 'mfa.setup.step.qr' | translate }}</span>
        <span>›</span>
        <span [class.font-bold]="step() === 'verify'">3. {{ 'mfa.setup.step.verify' | translate }}</span>
        <span>›</span>
        <span [class.font-bold]="step() === 'backup' || step() === 'done'">4. {{ 'mfa.setup.step.backup' | translate }}</span>
      </div>

      @switch (step()) {
        @case ('intro') {
          <p class="mb-4">{{ 'mfa.setup.intro.body' | translate }}</p>
          <ul class="list-disc pl-6 mb-6 text-gray-700">
            <li>{{ 'mfa.setup.intro.bullet1' | translate }}</li>
            <li>{{ 'mfa.setup.intro.bullet2' | translate }}</li>
            <li>{{ 'mfa.setup.intro.bullet3' | translate }}</li>
          </ul>
          <button
            class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            [disabled]="facade.loading()"
            (click)="startEnroll()"
          >
            {{ 'mfa.setup.intro.cta' | translate }}
          </button>
        }
        @case ('qr') {
          <p class="mb-4">{{ 'mfa.setup.qr.body' | translate }}</p>
          @if (facade.enroll(); as e) {
            <img
              [src]="'data:image/png;base64,' + e.qr_png_b64"
              [alt]="'mfa.setup.qr.alt' | translate"
              class="mx-auto mb-4 w-48 h-48 border rounded"
            />
            <details class="mb-4">
              <summary class="cursor-pointer text-sm text-gray-600">
                {{ 'mfa.setup.qr.show_secret' | translate }}
              </summary>
              <code class="block mt-2 p-2 bg-gray-100 rounded font-mono text-sm break-all">
                {{ e.secret_b32 }}
              </code>
              <button
                type="button"
                class="mt-2 text-sm text-blue-600 hover:underline"
                (click)="copySecret(e.secret_b32)"
              >
                {{ 'mfa.setup.qr.copy' | translate }}
              </button>
              @if (copied()) {
                <span class="ml-2 text-sm text-green-600">✓ {{ 'common.copied' | translate }}</span>
              }
            </details>
          }
          <button
            class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
            (click)="step.set('verify')"
          >
            {{ 'mfa.setup.qr.cta' | translate }}
          </button>
        }
        @case ('verify') {
          <p class="mb-4">{{ 'mfa.setup.verify.body' | translate }}</p>
          <app-totp-input
            #verifyTotp
            (codeChange)="code.set($event)"
            (codeComplete)="confirmEnroll()"
          />
          <button
            class="mt-6 w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            [disabled]="code().length !== 6 || facade.loading()"
            (click)="confirmEnroll()"
          >
            {{ 'mfa.setup.verify.cta' | translate }}
          </button>
        }
        @case ('backup') {
          <p class="mb-2">{{ 'mfa.setup.backup.body' | translate }}</p>
          <p class="text-sm text-amber-700 bg-amber-50 border border-amber-200 p-3 rounded mb-4">
            ⚠ {{ 'mfa.setup.backup.warning' | translate }}
          </p>
          @if (facade.backupCodes(); as codes) {
            <ul class="grid grid-cols-2 gap-2 font-mono text-base mb-4">
              @for (c of codes; track c) {
                <li class="bg-gray-100 px-3 py-2 rounded">{{ c }}</li>
              }
            </ul>
            <div class="flex gap-2 mb-6">
              <button
                type="button"
                class="border px-3 py-2 rounded text-sm hover:bg-gray-50"
                (click)="downloadCodes(codes)"
              >
                {{ 'mfa.setup.backup.download' | translate }}
              </button>
              <button
                type="button"
                class="border px-3 py-2 rounded text-sm hover:bg-gray-50"
                (click)="copyCodes(codes)"
              >
                {{ 'mfa.setup.backup.copy' | translate }}
              </button>
            </div>
          }
          <label class="flex items-start gap-2 mb-4 text-sm">
            <input type="checkbox" [checked]="confirmedSaved()" (change)="confirmedSaved.set(!confirmedSaved())" />
            <span>{{ 'mfa.setup.backup.confirm_saved' | translate }}</span>
          </label>
          <button
            class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            [disabled]="!confirmedSaved()"
            (click)="step.set('done')"
          >
            {{ 'mfa.setup.backup.cta' | translate }}
          </button>
        }
        @case ('done') {
          <p class="text-green-700 bg-green-50 border border-green-200 p-3 rounded mb-4">
            ✓ {{ 'mfa.setup.done.body' | translate }}
          </p>
          <a routerLink="/settings/security" class="text-blue-600 hover:underline">
            {{ 'mfa.setup.done.cta' | translate }}
          </a>
        }
      }
    </div>
  `,
})
export class MfaSetupComponent {
  facade = inject(MfaFacade);
  private router = inject(Router);

  step = signal<Step>('intro');
  code = signal('');
  copied = signal(false);
  confirmedSaved = signal(false);

  @ViewChild('verifyTotp') verifyTotp?: TotpInputComponent;

  isFinal = computed(() => this.step() === 'done');

  async startEnroll(): Promise<void> {
    const ok = await this.facade.beginEnroll();
    if (ok) this.step.set('qr');
  }

  async confirmEnroll(): Promise<void> {
    if (this.code().length !== 6) return;
    const ok = await this.facade.confirmEnroll(this.code());
    if (ok) {
      this.step.set('backup');
    } else {
      this.code.set('');
      this.verifyTotp?.clear();
    }
  }

  copySecret(secret: string): void {
    navigator.clipboard?.writeText(secret).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    });
  }

  copyCodes(codes: string[]): void {
    navigator.clipboard?.writeText(codes.join('\n')).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    });
  }

  downloadCodes(codes: string[]): void {
    const blob = new Blob(
      [
        'StratTraderPro — MFA backup codes\n',
        '======================================\n',
        'Each code can be used exactly once.\n\n',
        ...codes.map(c => c + '\n'),
      ],
      { type: 'text/plain' },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'strattraderpro-backup-codes.txt';
    a.click();
    URL.revokeObjectURL(url);
  }
}
