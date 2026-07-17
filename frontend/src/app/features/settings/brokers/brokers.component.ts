/**
 * /settings/brokers — connect + manage broker accounts (M04).
 *
 * Two sections:
 *   1. Connected brokers — status badge, test-connection, remove (MFA-gated),
 *      and an admin-only flatten button (backend 403s non-staff — that's fine).
 *   2. Connect Alpaca Paper — write-only API key + secret form.
 */
import { Component, OnInit, computed, inject, signal } from '@angular/core';
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
import { AuthStore } from '../../../abstraction/stores/auth.store';
import { ModalComponent } from '../../shared/ui/modal.component';

/** Typed-confirmation word gating the irreversible flatten action (P0-4). */
const FLATTEN_CONFIRM_WORD = 'FLATTEN';

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
  imports: [CommonModule, ReactiveFormsModule, TranslateModule, DatePipe, RouterLink, ModalComponent],
  template: `
    <div class="mx-auto max-w-3xl p-6 space-y-8">
      <h1 class="text-2xl font-bold">{{ 'brokers.title' | translate }}</h1>

      <!-- ========== Connected brokers ========== -->
      <section class="border rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-4">{{ 'brokers.connected.title' | translate }}</h2>

        @if (facade.loading()) {
          <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
        } @else if (facade.accounts().length === 0) {
          <p class="text-sm text-gray-500">{{ 'brokers.connected.empty' | translate }}</p>
        } @else {
          <ul class="divide-y">
            @for (acct of facade.accounts(); track acct.id) {
              <li class="py-4">
                <div class="flex items-start justify-between">
                  <div>
                    <p class="font-medium">
                      {{ acct.nickname || acct.broker }}
                      <span class="ml-2 text-xs px-2 py-0.5 bg-gray-100 text-gray-700 rounded">{{ acct.mode }}</span>
                      @if (acct.is_default) {
                        <span class="ml-1 text-xs px-2 py-0.5 bg-blue-100 text-blue-800 rounded">
                          {{ 'brokers.connected.default' | translate }}
                        </span>
                      }
                    </p>
                    <p class="text-sm text-gray-500 font-mono">{{ acct.account_number || '—' }}</p>
                    <p class="text-xs text-gray-500">
                      {{ 'brokers.connected.last_connected' | translate }}:
                      {{ acct.last_connected_at ? (acct.last_connected_at | date:'medium') : '—' }}
                    </p>
                  </div>
                  <div class="text-right">
                    @switch (badge(acct)) {
                      @case ('connected') {
                        <span class="inline-block px-2 py-1 bg-green-100 text-green-800 text-xs rounded">
                          {{ 'brokers.status.connected' | translate }}
                        </span>
                      }
                      @case ('degraded') {
                        <span class="inline-block px-2 py-1 bg-amber-100 text-amber-800 text-xs rounded">
                          {{ 'brokers.status.degraded' | translate }}
                        </span>
                      }
                      @default {
                        <span class="inline-block px-2 py-1 bg-red-100 text-red-800 text-xs rounded">
                          {{ 'brokers.status.down' | translate }}
                        </span>
                      }
                    }
                  </div>
                </div>

                <!-- Row actions -->
                <div class="mt-3 flex flex-wrap gap-3 text-sm">
                  <button type="button" (click)="onTest(acct.id)"
                          class="text-blue-600 hover:underline">
                    {{ 'brokers.connected.test' | translate }}
                  </button>
                  <button type="button" (click)="startRemove(acct.id)"
                          class="text-red-600 hover:underline">
                    {{ 'brokers.connected.remove' | translate }}
                  </button>
                  @if (isStaff()) {
                    <button type="button" (click)="onFlatten(acct.id)"
                            class="text-amber-700 hover:underline">
                      {{ 'brokers.connected.flatten' | translate }}
                    </button>
                  }
                </div>

                <!-- Mode control (PAPER active; LIVE disabled until enabled) -->
                <div class="mt-3 flex items-center gap-2 text-xs">
                  <span class="text-gray-500">{{ 'brokers.mode.label' | translate }}:</span>
                  <div class="inline-flex rounded border overflow-hidden">
                    <button type="button" (click)="onSetMode(acct, 'PAPER')"
                            [class.bg-blue-600]="acct.mode === 'PAPER'"
                            [class.text-white]="acct.mode === 'PAPER'"
                            class="px-3 py-1">
                      {{ 'brokers.mode.paper' | translate }}
                    </button>
                    <button type="button" (click)="onSetMode(acct, 'LIVE')"
                            [attr.aria-disabled]="true"
                            [title]="'brokers.mode.live_soon' | translate"
                            class="px-3 py-1 border-l text-gray-500 cursor-not-allowed">
                      {{ 'brokers.mode.live' | translate }}
                    </button>
                  </div>
                </div>

                <!-- Test-connection result -->
                @if (testResults()[acct.id]; as tr) {
                  <div class="mt-2 text-xs bg-green-50 border border-green-200 text-green-800 rounded px-3 py-2">
                    {{ 'brokers.connected.account_number' | translate }}: {{ tr.account_number }} ·
                    {{ 'brokers.connected.buying_power' | translate }}: {{ fmtMoney(tr.buying_power, tr.currency) }}
                  </div>
                }

                <!-- MFA-gated remove prompt -->
                @if (removingId() === acct.id) {
                  <form [formGroup]="mfaForm" (ngSubmit)="confirmRemove(acct.id)"
                        class="mt-3 flex flex-wrap items-center gap-2">
                    <input type="text" inputmode="numeric" formControlName="mfa_code" maxlength="6"
                           autocomplete="one-time-code"
                           [placeholder]="'brokers.connected.mfa_placeholder' | translate"
                           class="border rounded px-3 py-2 font-mono text-sm w-32" />
                    <button type="submit" [disabled]="mfaForm.invalid"
                            class="bg-red-600 text-white px-3 py-2 rounded text-sm hover:bg-red-700 disabled:opacity-50">
                      {{ 'brokers.connected.confirm_remove' | translate }}
                    </button>
                    <button type="button" (click)="cancelRemove()"
                            class="px-3 py-2 rounded text-sm border hover:bg-gray-50">
                      {{ 'common.cancel' | translate }}
                    </button>
                  </form>
                }

                <!-- Per-row error (test / remove / flatten) -->
                @if (rowErrors()[acct.id]; as err) {
                  <p class="mt-2 text-xs text-red-700">
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
      </section>

      <!-- ========== Flatten confirmation (P0-4) — irreversible, typed confirm ========== -->
      <app-modal
        [open]="flatteningId() !== null"
        [heading]="'brokers.flatten.title' | translate"
        (closed)="cancelFlatten()">
        <p class="text-sm text-slate-700 mb-4">{{ 'brokers.flatten.warning' | translate }}</p>
        <label class="block text-sm font-medium mb-1" for="flatten-confirm">
          {{ 'brokers.flatten.type_to_confirm' | translate }}
        </label>
        <input id="flatten-confirm" type="text" autocomplete="off"
               [value]="flattenConfirm()"
               (input)="flattenConfirm.set($any($event.target).value)"
               class="w-full border rounded px-3 py-2 font-mono text-sm mb-4" />
        <div class="flex justify-end gap-2">
          <button type="button" (click)="cancelFlatten()"
                  class="px-3 py-2 rounded text-sm border hover:bg-gray-50">
            {{ 'common.cancel' | translate }}
          </button>
          <button type="button" (click)="confirmFlatten()"
                  [disabled]="!flattenConfirmed()"
                  class="bg-red-600 text-white px-3 py-2 rounded text-sm hover:bg-red-700 disabled:opacity-50">
            {{ 'brokers.flatten.confirm' | translate }}
          </button>
        </div>
      </app-modal>

      <!-- ========== Connect Alpaca Paper ========== -->
      <section class="border rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-1">{{ 'brokers.connect.title' | translate }}</h2>
        <p class="text-sm text-gray-600 mb-4">
          {{ 'brokers.connect.help' | translate }}
          <a routerLink="/help/alpaca-paper-connect"
             class="text-blue-600 hover:underline">{{ 'brokers.connect.help_link' | translate }}</a>
        </p>

        <form [formGroup]="connectForm" (ngSubmit)="onConnect()" class="space-y-3 max-w-md">
          <div>
            <label class="block text-sm font-medium mb-1">{{ 'brokers.connect.api_key_id' | translate }}</label>
            <input type="text" formControlName="api_key_id" autocomplete="off"
                   class="w-full border rounded px-3 py-2 font-mono text-sm" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">{{ 'brokers.connect.api_secret' | translate }}</label>
            <input type="password" formControlName="api_secret" autocomplete="new-password"
                   class="w-full border rounded px-3 py-2 font-mono text-sm" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">
              {{ 'brokers.connect.nickname' | translate }}
              <span class="text-gray-500 font-normal">({{ 'brokers.connect.optional' | translate }})</span>
            </label>
            <input type="text" formControlName="nickname" class="w-full border rounded px-3 py-2 text-sm" />
          </div>
          <button type="submit" [disabled]="connectForm.invalid || facade.loading()"
                  class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50">
            {{ 'brokers.connect.submit' | translate }}
          </button>
        </form>

        @if (connectResult(); as r) {
          <div class="mt-4 p-3 bg-green-50 border border-green-200 rounded text-sm text-green-800">
            ✓ {{ 'brokers.connect.success' | translate }} —
            {{ 'brokers.connected.account_number' | translate }}: {{ r.account_number }} ·
            {{ 'brokers.connected.buying_power' | translate }}: {{ fmtMoney(r.buying_power) }}
          </div>
        }
        @if (connectError(); as err) {
          <p class="mt-4 text-sm text-red-700">
            @if (knownError(err.code)) {
              {{ ('brokers.error.' + err.code) | translate }}
            } @else {
              {{ err.message }}
            }
          </p>
        }
      </section>

      <!-- ========== Connect TradeStation ========== -->
      <!-- §7.9: TradeStation is not enabled in any deployed config (flag OFF,
           M05 follow-up). Don't show a button that looks functional — disable it
           and say so honestly rather than 404/500 on click. -->
      <section class="border rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-1">{{ 'brokers.connect_tradestation.title' | translate }}</h2>
        <p class="text-sm text-gray-600 mb-4">{{ 'brokers.connect_tradestation.help' | translate }}</p>
        <button type="button" disabled aria-disabled="true"
                class="bg-gray-300 text-gray-600 px-4 py-2 rounded cursor-not-allowed">
          {{ 'brokers.connect_tradestation.button' | translate }}
        </button>
        <p class="mt-2 text-xs text-gray-500">{{ 'brokers.connect_tradestation.unavailable' | translate }}</p>
        @if (tsError(); as err) {
          <p class="mt-4 text-sm text-red-700">
            @if (knownError(err.code)) {
              {{ ('brokers.error.' + err.code) | translate }}
            } @else {
              {{ err.message }}
            }
          </p>
        }
      </section>
    </div>
  `,
})
export class BrokersComponent implements OnInit {
  facade = inject(BrokersFacade);
  private fb = inject(FormBuilder);
  private store = inject(AuthStore);

  /** Flatten is admin-gated server-side (403 otherwise); don't render it to
   * users who can't use it (P0-4). */
  isStaff = computed(() => this.store.user()?.is_staff === true);

  connectResult = signal<BrokerConnectResult | null>(null);
  connectError = signal<ApiError | null>(null);
  tsError = signal<ApiError | null>(null);
  testResults = signal<Record<string, BrokerTestConnectionResult>>({});
  rowErrors = signal<Record<string, ApiError>>({});
  removingId = signal<string | null>(null);

  // Flatten confirmation (P0-4): the account pending flatten + typed-confirm text.
  flatteningId = signal<string | null>(null);
  flattenConfirm = signal('');
  flattenConfirmed = computed(() => this.flattenConfirm() === FLATTEN_CONFIRM_WORD);

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

  /** Open the typed-confirm modal — flatten is irreversible, so it must NOT
   * fire on a single click (P0-4). */
  onFlatten(id: string): void {
    this._clearRowError(id);
    this.flattenConfirm.set('');
    this.flatteningId.set(id);
  }

  cancelFlatten(): void {
    this.flatteningId.set(null);
    this.flattenConfirm.set('');
  }

  async confirmFlatten(): Promise<void> {
    const id = this.flatteningId();
    if (!id || !this.flattenConfirmed()) { return; }
    this.flatteningId.set(null);
    this.flattenConfirm.set('');
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
