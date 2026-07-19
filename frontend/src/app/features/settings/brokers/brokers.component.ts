/**
 * /settings/brokers — connect + manage broker accounts (M04).
 *
 * Two sections ("Industry" design system):
 *   1. Connected brokers — status chip, test-connection, remove (MFA-gated),
 *      and an admin-only flatten button (backend 403s non-staff — that's fine).
 *   2. Connect Alpaca Paper — write-only API key + secret form.
 */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { ApiError } from '../../../core/models/auth.models';
import {
  BrokerAccount,
  BrokerConnectResult,
  BrokerMode,
  BrokerTestConnectionResult,
} from '../../../core/models/brokers.models';
import { BrokersFacade } from '../../../abstraction/facades/brokers.facade';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { StatusChipComponent } from '../../shared/ui/status-chip.component';

/** Error codes that have a dedicated translated message. */
const KNOWN_ERRORS = new Set([
  'BROKER_LIVE_KEYS_FORBIDDEN',
  'BROKER_AUTH_FAILED',
  'MFA_REQUIRED',
  'BROKER_RATE_LIMITED',
  'NO_BROKER_CONNECTED',
  'BROKER_ALREADY_CONNECTED',
  'BROKER_DISABLED',
  'BROKER_UNAVAILABLE',
  'VALIDATION_ERROR',
  'LIVE_TRADING_DISABLED',
]);

@Component({
  selector: 'app-brokers',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    TranslateModule,
    DatePipe,
    RouterLink,
    ButtonComponent,
    CardComponent,
    PageHeaderComponent,
    StatusChipComponent,
  ],
  template: `
    <div class="mx-auto max-w-3xl p-6">
      <app-page-header [heading]="'brokers.title' | translate" />

      <div class="flex flex-col gap-s6">
        <!-- ========== Connected brokers ========== -->
        <app-card>
          <h2 class="m-0 mb-s3 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
            {{ 'brokers.connected.title' | translate }}
          </h2>

          @if (facade.loading()) {
            <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
          } @else if (facade.accounts().length === 0) {
            <p class="text-sm text-neutral-700">{{ 'brokers.connected.empty' | translate }}</p>
          } @else {
            <ul class="divide-y divide-divider">
              @for (acct of facade.accounts(); track acct.id) {
                <li class="py-s4 first:pt-0 last:pb-0">
                  <div class="flex items-start justify-between gap-3.5">
                    <div>
                      <div class="flex flex-wrap items-center gap-2">
                        <span class="text-base font-bold text-ink">{{ acct.nickname || acct.broker }}</span>
                        <app-status-chip [status]="acct.mode">{{ acct.mode }}</app-status-chip>
                        @if (acct.is_default) {
                          <app-status-chip status="DEFAULT">
                            {{ 'brokers.connected.default' | translate }}
                          </app-status-chip>
                        }
                      </div>
                      <p class="mt-1 font-mono text-xs text-neutral-700">{{ acct.account_number || '—' }}</p>
                      <p class="font-mono text-xs text-neutral-700">
                        {{ 'brokers.connected.last_connected' | translate }}:
                        {{ acct.last_connected_at ? (acct.last_connected_at | date:'medium') : '—' }}
                      </p>
                    </div>
                    <app-status-chip [status]="badge(acct)" [dot]="true" class="shrink-0">
                      {{ ('brokers.status.' + badge(acct)) | translate }}
                    </app-status-chip>
                  </div>

                  <!-- Row actions + mode segmented control -->
                  <div class="mt-s3 flex flex-wrap items-center gap-2">
                    <app-button variant="ghost" (clicked)="onTest(acct.id)">
                      {{ 'brokers.connected.test' | translate }}
                    </app-button>
                    <app-button variant="ghost" (clicked)="startRemove(acct.id)">
                      <span class="text-down">{{ 'brokers.connected.remove' | translate }}</span>
                    </app-button>
                    <app-button variant="ghost" (clicked)="onFlatten(acct.id)">
                      <span class="text-warn-deep">{{ 'brokers.connected.flatten' | translate }}</span>
                    </app-button>
                  </div>

                  <!-- Mode control (PAPER active; LIVE disabled until enabled) -->
                  <div class="mt-s3 flex items-center gap-2 text-xs">
                    <span class="text-neutral-700">{{ 'brokers.mode.label' | translate }}:</span>
                    <div class="inline-flex overflow-hidden rounded-none border border-divider">
                      <button type="button" (click)="onSetMode(acct, 'PAPER')"
                              class="px-3 py-1 font-heading font-semibold uppercase tracking-wide"
                              [class.bg-accent-700]="acct.mode === 'PAPER'"
                              [class.text-bg]="acct.mode === 'PAPER'">
                        {{ 'brokers.mode.paper' | translate }}
                      </button>
                      <button type="button"
                              [attr.aria-disabled]="true"
                              [title]="'brokers.mode.live_soon' | translate"
                              class="cursor-not-allowed border-l border-divider px-3 py-1 font-heading font-semibold uppercase tracking-wide text-neutral-700 opacity-45">
                        {{ 'brokers.mode.live' | translate }}
                      </button>
                    </div>
                  </div>

                  <!-- Test-connection result -->
                  @if (testResults()[acct.id]; as tr) {
                    <div class="mt-2 rounded-none border border-divider bg-up-tint px-3 py-2 font-mono text-xs text-up-deep">
                      {{ 'brokers.connected.account_number' | translate }}: {{ tr.account_number }} ·
                      {{ 'brokers.connected.buying_power' | translate }}: {{ fmtMoney(tr.buying_power, tr.currency) }}
                    </div>
                  }

                  <!-- MFA-gated remove prompt — the one inline MFA confirm
                       pattern: input → danger confirm → secondary cancel -->
                  @if (removingId() === acct.id) {
                    <form [formGroup]="mfaForm" (ngSubmit)="confirmRemove(acct.id)"
                          class="mt-s3 flex flex-wrap items-center gap-2 border-t border-divider pt-s3">
                      <input type="text" inputmode="numeric" formControlName="mfa_code" maxlength="6"
                             autocomplete="one-time-code"
                             [placeholder]="'brokers.connected.mfa_placeholder' | translate"
                             class="w-32 rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-accent focus:outline-none" />
                      <app-button type="submit" variant="danger" [disabled]="mfaForm.invalid">
                        {{ 'brokers.connected.confirm_remove' | translate }}
                      </app-button>
                      <app-button variant="secondary" (clicked)="cancelRemove()">
                        {{ 'common.cancel' | translate }}
                      </app-button>
                    </form>
                  }

                  <!-- Per-row error (test / remove / flatten) -->
                  @if (rowErrors()[acct.id]; as err) {
                    <p class="mt-2 text-xs text-down-deep">
                      @if (knownError(err.code)) {
                        {{ ('brokers.error.' + err.code) | translate }}
                      } @else {
                        {{ err.message }}
                      }
                    </p>
                  }
                </li>
              }
            </ul>
          }
        </app-card>

        <!-- ========== Connect Alpaca Paper ========== -->
        <app-card>
          <h2 class="m-0 mb-1 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
            {{ 'brokers.connect.title' | translate }}
          </h2>
          <p class="mb-s3 text-sm text-neutral-700">
            {{ 'brokers.connect.help' | translate }}
            <a routerLink="/help/alpaca-paper-connect"
               class="text-accent-700 hover:underline">{{ 'brokers.connect.help_link' | translate }}</a>
          </p>

          <form [formGroup]="connectForm" (ngSubmit)="onConnect()" class="max-w-md space-y-3">
            <div>
              <label class="mb-1 block text-xs font-medium text-neutral-700">{{ 'brokers.connect.api_key_id' | translate }}</label>
              <input type="text" formControlName="api_key_id" autocomplete="off"
                     class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-accent focus:outline-none" />
            </div>
            <div>
              <label class="mb-1 block text-xs font-medium text-neutral-700">{{ 'brokers.connect.api_secret' | translate }}</label>
              <input type="password" formControlName="api_secret" autocomplete="new-password"
                     class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-accent focus:outline-none" />
            </div>
            <div>
              <label class="mb-1 block text-xs font-medium text-neutral-700">
                {{ 'brokers.connect.nickname' | translate }}
                <span class="font-normal text-neutral-500">({{ 'brokers.connect.optional' | translate }})</span>
              </label>
              <input type="text" formControlName="nickname"
                     class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none" />
            </div>
            <app-button type="submit" variant="primary" [disabled]="connectForm.invalid || facade.loading()">
              {{ 'brokers.connect.submit' | translate }}
            </app-button>
          </form>

          @if (connectResult(); as r) {
            <div class="mt-s3 rounded-none border border-divider bg-up-tint p-3 text-sm text-up-deep">
              ✓ {{ 'brokers.connect.success' | translate }} —
              {{ 'brokers.connected.account_number' | translate }}: <span class="font-mono">{{ r.account_number }}</span> ·
              {{ 'brokers.connected.buying_power' | translate }}: <span class="font-mono">{{ fmtMoney(r.buying_power) }}</span>
            </div>
          }
          @if (connectError(); as err) {
            <p class="mt-s3 text-sm text-down-deep">
              @if (knownError(err.code)) {
                {{ ('brokers.error.' + err.code) | translate }}
              } @else {
                {{ err.message }}
              }
            </p>
          }
        </app-card>

        <!-- ========== Connect TradeStation ========== -->
        <!-- §7.9: TradeStation is not enabled in any deployed config (flag OFF,
             M05 follow-up). Don't show a button that looks functional — disable it
             and say so honestly rather than 404/500 on click. Kept as a native
             button to preserve the exact disabled + aria-disabled markup. -->
        <app-card>
          <h2 class="m-0 mb-1 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
            {{ 'brokers.connect_tradestation.title' | translate }}
          </h2>
          <p class="mb-s3 text-sm text-neutral-700">{{ 'brokers.connect_tradestation.help' | translate }}</p>
          <button type="button" disabled aria-disabled="true"
                  class="inline-flex w-fit cursor-not-allowed items-center justify-center rounded-none border border-divider bg-transparent px-3 py-1.5 font-heading text-sm font-semibold leading-tight text-ink opacity-45">
            {{ 'brokers.connect_tradestation.button' | translate }}
          </button>
          <p class="mt-2 text-xs text-neutral-700">{{ 'brokers.connect_tradestation.unavailable' | translate }}</p>
          @if (tsError(); as err) {
            <p class="mt-s3 text-sm text-down-deep">
              @if (knownError(err.code)) {
                {{ ('brokers.error.' + err.code) | translate }}
              } @else {
                {{ err.message }}
              }
            </p>
          }
        </app-card>
      </div>
    </div>
  `,
})
export class BrokersComponent implements OnInit {
  facade = inject(BrokersFacade);
  private fb = inject(FormBuilder);

  connectResult = signal<BrokerConnectResult | null>(null);
  connectError = signal<ApiError | null>(null);
  tsError = signal<ApiError | null>(null);
  testResults = signal<Record<string, BrokerTestConnectionResult>>({});
  rowErrors = signal<Record<string, ApiError>>({});
  removingId = signal<string | null>(null);

  connectForm = this.fb.nonNullable.group({
    api_key_id: ['', Validators.required],
    api_secret: ['', Validators.required],
    nickname: [''],
  });

  mfaForm = this.fb.nonNullable.group({
    mfa_code: ['', [Validators.required, Validators.minLength(6), Validators.maxLength(6)]],
  });

  ngOnInit(): void {
    void this.facade.load();
  }

  /** Derive the status badge variant from status + stream_status. */
  badge(acct: BrokerAccount): 'connected' | 'degraded' | 'down' {
    if (acct.status && acct.status.toUpperCase().includes('ERROR')) { return 'down'; }
    switch (acct.stream_status) {
      case 'CONNECTED': return 'connected';
      case 'DEGRADED': return 'degraded';
      default: return 'down';
    }
  }

  async onConnect(): Promise<void> {
    if (this.connectForm.invalid) { return; }
    this.connectResult.set(null);
    this.connectError.set(null);
    const { api_key_id, api_secret, nickname } = this.connectForm.getRawValue();
    const res = await this.facade.connect({
      api_key_id,
      api_secret,
      broker: 'ALPACA',
      mode: 'PAPER',
      nickname: nickname || undefined,
    });
    if (res.ok) {
      this.connectResult.set(res.value);
      this.connectForm.reset(); // wipes the secret from memory
    } else {
      this.connectError.set(res.error);
    }
  }

  async onTest(id: string): Promise<void> {
    this._clearRowError(id);
    const res = await this.facade.testConnection(id);
    if (res.ok) {
      this.testResults.set({ ...this.testResults(), [id]: res.value });
    } else {
      this._setRowError(id, res.error);
    }
  }

  startRemove(id: string): void {
    this._clearRowError(id);
    this.mfaForm.reset();
    this.removingId.set(id);
  }

  cancelRemove(): void {
    this.removingId.set(null);
    this.mfaForm.reset();
  }

  async confirmRemove(id: string): Promise<void> {
    if (this.mfaForm.invalid) { return; }
    const { mfa_code } = this.mfaForm.getRawValue();
    const res = await this.facade.remove(id, mfa_code);
    if (res.ok) {
      this.removingId.set(null);
      this.mfaForm.reset();
    } else if (res.error) {
      // 403 MFA_REQUIRED (or a wrong code) — keep the prompt open and re-ask.
      this._setRowError(id, res.error);
    }
  }

  async onFlatten(id: string): Promise<void> {
    this._clearRowError(id);
    const res = await this.facade.flatten(id);
    if (!res.ok) {
      this._setRowError(id, res.error);
    }
  }

  /** Switch a broker's mode. LIVE 403s with LIVE_TRADING_DISABLED (mapped below). */
  async onSetMode(acct: BrokerAccount, mode: BrokerMode): Promise<void> {
    this._clearRowError(acct.id);
    const res = await this.facade.setMode(acct.id, mode);
    if (!res.ok) {
      this._setRowError(acct.id, res.error);
    }
  }

  async onConnectTradeStation(): Promise<void> {
    this.tsError.set(null);
    const res = await this.facade.tradestationOauthStart();
    if (res.ok) {
      window.location.href = res.value.authorize_url;
    } else {
      this.tsError.set(res.error);
    }
  }

  /** True when the code has a dedicated translated message under brokers.error.*. */
  knownError(code: string): boolean {
    return KNOWN_ERRORS.has(code);
  }

  fmtMoney(value: string, currency = 'USD'): string {
    const n = Number(value);
    if (!isFinite(n)) { return value; }
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(n);
  }

  private _setRowError(id: string, err: ApiError): void {
    this.rowErrors.set({ ...this.rowErrors(), [id]: err });
  }

  private _clearRowError(id: string): void {
    const next = { ...this.rowErrors() };
    delete next[id];
    this.rowErrors.set(next);
  }
}
