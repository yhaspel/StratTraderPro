/**
 * /settings/security/mfa/setup — multi-step enrollment wizard
 * ("Industry" design system; flow untouched).
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
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';

type Step = 'intro' | 'qr' | 'verify' | 'backup' | 'done';

@Component({
  selector: 'app-mfa-setup',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    TranslateModule,
    TotpInputComponent,
    ButtonComponent,
    CardComponent,
    PageHeaderComponent,
  ],
  template: `
    <div class="mx-auto max-w-xl p-6">
      <app-page-header [heading]="'mfa.setup.title' | translate" />

      @if (facade.error(); as err) {
        <div class="mb-s3 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
          {{ 'mfa.error.' + err.code | translate : { default: err.message } }}
        </div>
      }

      <app-card>
        <!-- step indicator -->
        <div class="mb-s6 flex gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-neutral-700">
          <span [class.font-bold]="step() === 'intro'" [class.text-accent-700]="step() === 'intro'">1. {{ 'mfa.setup.step.intro' | translate }}</span>
          <span>›</span>
          <span [class.font-bold]="step() === 'qr'" [class.text-accent-700]="step() === 'qr'">2. {{ 'mfa.setup.step.qr' | translate }}</span>
          <span>›</span>
          <span [class.font-bold]="step() === 'verify'" [class.text-accent-700]="step() === 'verify'">3. {{ 'mfa.setup.step.verify' | translate }}</span>
          <span>›</span>
          <span [class.font-bold]="step() === 'backup' || step() === 'done'"
                [class.text-accent-700]="step() === 'backup' || step() === 'done'">4. {{ 'mfa.setup.step.backup' | translate }}</span>
        </div>

        @switch (step()) {
          @case ('intro') {
            <p class="mb-s3 text-sm text-ink">{{ 'mfa.setup.intro.body' | translate }}</p>
            <ul class="mb-s6 list-disc pl-6 text-sm text-neutral-700">
              <li>{{ 'mfa.setup.intro.bullet1' | translate }}</li>
              <li>{{ 'mfa.setup.intro.bullet2' | translate }}</li>
              <li>{{ 'mfa.setup.intro.bullet3' | translate }}</li>
            </ul>
            <app-button variant="primary" [disabled]="facade.loading()" (clicked)="startEnroll()">
              {{ 'mfa.setup.intro.cta' | translate }}
            </app-button>
          }
          @case ('qr') {
            <p class="mb-s3 text-sm text-ink">{{ 'mfa.setup.qr.body' | translate }}</p>
            @if (facade.enroll(); as e) {
              <img
                [src]="'data:image/png;base64,' + e.qr_png_b64"
                [alt]="'mfa.setup.qr.alt' | translate"
                class="mx-auto mb-s3 h-48 w-48 rounded-none border border-divider bg-bg"
              />
              <details class="mb-s3">
                <summary class="cursor-pointer text-sm text-neutral-700">
                  {{ 'mfa.setup.qr.show_secret' | translate }}
                </summary>
                <code class="mt-2 block break-all rounded-none border border-divider bg-surface p-2 font-mono text-sm text-ink">
                  {{ e.secret_b32 }}
                </code>
                <app-button variant="ghost" class="mt-2" (clicked)="copySecret(e.secret_b32)">
                  {{ 'mfa.setup.qr.copy' | translate }}
                </app-button>
                @if (copied()) {
                  <span class="ml-2 text-sm text-accent-700">✓ {{ 'common.copied' | translate }}</span>
                }
              </details>
            }
            <app-button variant="primary" (clicked)="step.set('verify')">
              {{ 'mfa.setup.qr.cta' | translate }}
            </app-button>
          }
          @case ('verify') {
            <p class="mb-s3 text-sm text-ink">{{ 'mfa.setup.verify.body' | translate }}</p>
            <app-totp-input
              #verifyTotp
              (codeChange)="code.set($event)"
              (codeComplete)="confirmEnroll()"
            />
            <div class="mt-s6">
              <app-button
                variant="primary"
                [disabled]="code().length !== 6 || facade.loading()"
                (clicked)="confirmEnroll()"
              >
                {{ 'mfa.setup.verify.cta' | translate }}
              </app-button>
            </div>
          }
          @case ('backup') {
            <p class="mb-2 text-sm text-ink">{{ 'mfa.setup.backup.body' | translate }}</p>
            <p class="mb-s3 rounded-none border border-warn bg-warn-tint p-3 text-sm text-warn-deep">
              ⚠ {{ 'mfa.setup.backup.warning' | translate }}
            </p>
            @if (facade.backupCodes(); as codes) {
              <ul class="mb-s3 grid grid-cols-2 gap-2 font-mono text-base">
                @for (c of codes; track c) {
                  <li class="rounded-none border border-divider bg-surface px-3 py-2">{{ c }}</li>
                }
              </ul>
              <div class="mb-s6 flex gap-2">
                <app-button variant="secondary" (clicked)="downloadCodes(codes)">
                  {{ 'mfa.setup.backup.download' | translate }}
                </app-button>
                <app-button variant="secondary" (clicked)="copyCodes(codes)">
                  {{ 'mfa.setup.backup.copy' | translate }}
                </app-button>
              </div>
            }
            <label class="mb-s3 flex items-start gap-2 text-sm text-ink">
              <input type="checkbox" [checked]="confirmedSaved()" (change)="confirmedSaved.set(!confirmedSaved())"
                     class="mt-0.5 h-[15px] w-[15px] rounded-none accent-accent" />
              <span>{{ 'mfa.setup.backup.confirm_saved' | translate }}</span>
            </label>
            <app-button variant="primary" [disabled]="!confirmedSaved()" (clicked)="step.set('done')">
              {{ 'mfa.setup.backup.cta' | translate }}
            </app-button>
          }
          @case ('done') {
            <p class="mb-s3 rounded-none border border-divider bg-accent-100 p-3 text-sm text-accent-800">
              ✓ {{ 'mfa.setup.done.body' | translate }}
            </p>
            <a routerLink="/settings/security" class="text-sm text-accent-700 hover:underline">
              {{ 'mfa.setup.done.cta' | translate }}
            </a>
          }
        }
      </app-card>
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
