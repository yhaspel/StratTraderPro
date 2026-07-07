/** /risk — risk envelope editor, kill switches, and audit feeds (M08).
 *
 * Four sections:
 *   (a) Profile editor — a ReactiveForm over the full RiskProfile; backend
 *       VALIDATION_ERROR details are mapped to inline field messages.
 *   (b) Active kill switches — a personal (L1/USER) halt card gated behind an
 *       MFA prompt, plus release controls for any other active switches.
 *   (c) Risk events feed.
 *   (d) Sizing decisions feed (last ~50).
 */
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { ApiError } from '../../core/models/auth.models';
import { KillSwitch, RiskProfile } from '../../core/models/risk.models';
import { RiskFacade } from '../../abstraction/facades/risk.facade';

/** Numeric profile fields (rendered as number inputs, in display order). */
const NUMERIC_FIELDS = [
  { key: 'risk_per_trade_pct', step: '0.01' },
  { key: 'max_position_pct', step: '0.01' },
  { key: 'max_concurrent', step: '1' },
  { key: 'daily_loss_usd', step: '1' },
  { key: 'daily_loss_pct', step: '0.01' },
  { key: 'leverage_cap', step: '0.1' },
  { key: 'soft_stop_pct', step: '0.01' },
  { key: 'hard_stop_pct', step: '0.01' },
  { key: 'atr_factor', step: '0.1' },
] as const;

const ASSET_CLASSES = ['STOCK', 'ETF', 'OPTION', 'FUTURE'] as const;

/** Reset target for the "Defaults" button. */
const DEFAULTS: RiskProfile = {
  risk_per_trade_pct: 1,
  max_position_pct: 10,
  max_concurrent: 5,
  daily_loss_usd: 1000,
  daily_loss_pct: 5,
  leverage_cap: 1,
  permitted_asset_classes: ['STOCK', 'ETF'],
  soft_stop_pct: 3,
  hard_stop_pct: 6,
  strict_mode: true,
  atr_factor: 2,
};

/** Risk error codes with a dedicated translated message. */
const KNOWN_ERRORS = new Set([
  'HALT_LOCKED',
  'MFA_REQUIRED',
  'FORBIDDEN',
  'VALIDATION_ERROR',
  'UNKNOWN',
]);

@Component({
  selector: 'app-risk',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, TranslateModule, DatePipe],
  template: `
    <div class="mx-auto max-w-5xl p-6 space-y-8">
      <h1 class="text-2xl font-bold">{{ 'risk.title' | translate }}</h1>

      <!-- ========== (a) Profile editor ========== -->
      <section class="border rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-4">{{ 'risk.profile.title' | translate }}</h2>

        @if (facade.loading() && !facade.profile()) {
          <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
        } @else {
          <form [formGroup]="profileForm" (ngSubmit)="onSave()" class="space-y-5">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              @for (f of numericFields; track f.key) {
                <div>
                  <label class="block text-sm font-medium mb-1" [attr.for]="f.key">
                    {{ ('risk.profile.' + f.key) | translate }}
                  </label>
                  <input type="number" [id]="f.key" [formControlName]="f.key" [step]="f.step"
                         class="w-full border rounded px-3 py-2 font-mono text-sm" />
                  <p class="mt-1 text-xs text-gray-400">{{ ('risk.profile.' + f.key + '_help') | translate }}</p>
                  @if (fieldErrors()[f.key]; as errs) {
                    <p class="mt-1 text-xs text-red-700">{{ errs.join(' ') }}</p>
                  }
                </div>
              }
            </div>

            <!-- strict_mode -->
            <div>
              <label class="inline-flex items-center gap-2 text-sm font-medium">
                <input type="checkbox" formControlName="strict_mode" class="rounded" />
                {{ 'risk.profile.strict_mode' | translate }}
              </label>
              <p class="mt-1 text-xs text-gray-400">{{ 'risk.profile.strict_mode_help' | translate }}</p>
            </div>

            <!-- permitted_asset_classes multi-select -->
            <div>
              <span class="block text-sm font-medium mb-1">{{ 'risk.profile.permitted_asset_classes' | translate }}</span>
              <div class="flex flex-wrap gap-3">
                @for (cls of assetClasses; track cls) {
                  <label class="inline-flex items-center gap-2 text-sm border rounded px-3 py-1.5 cursor-pointer"
                         [class.bg-blue-50]="hasClass(cls)" [class.border-blue-300]="hasClass(cls)">
                    <input type="checkbox" [checked]="hasClass(cls)" (change)="toggleClass(cls)" class="rounded" />
                    {{ ('risk.profile.asset_class.' + cls) | translate }}
                  </label>
                }
              </div>
              @if (fieldErrors()['permitted_asset_classes']; as errs) {
                <p class="mt-1 text-xs text-red-700">{{ errs.join(' ') }}</p>
              }
            </div>

            <!-- Non-field / cross-field validation errors (e.g. soft/hard stop) -->
            @if (generalErrors().length > 0) {
              <div class="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm" role="alert">
                @for (msg of generalErrors(); track msg) {
                  <p>{{ msg }}</p>
                }
              </div>
            }

            @if (savedToast()) {
              <p class="text-sm text-green-700">✓ {{ 'risk.profile.saved' | translate }}</p>
            }

            <div class="flex gap-3">
              <button type="submit" [disabled]="profileForm.invalid"
                      class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50">
                {{ 'risk.save' | translate }}
              </button>
              <button type="button" (click)="onDefaults()"
                      class="px-4 py-2 rounded border hover:bg-gray-50">
                {{ 'risk.defaults' | translate }}
              </button>
            </div>
          </form>
        }
      </section>

      <!-- ========== (b) Active kill switches ========== -->
      <section class="border rounded-lg p-6 space-y-4">
        <h2 class="text-lg font-semibold">{{ 'risk.switch.title' | translate }}</h2>

        <!-- Personal (L1 / USER) halt card -->
        <div class="border rounded-lg p-4"
             [class.border-red-300]="!!userHalt()" [class.bg-red-50]="!!userHalt()">
          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="font-medium">{{ 'risk.switch.USER' | translate }}</p>
              @if (userHalt(); as ks) {
                <p class="text-sm text-red-700">
                  {{ 'risk.switch.active' | translate }} ·
                  {{ 'risk.switch.since' | translate }} {{ ks.created_at | date:'short' }}
                  @if (ks.reason) { · {{ ('risk.reason.' + ks.reason) | translate }} }
                </p>
              } @else {
                <p class="text-sm text-gray-500">{{ 'risk.switch.inactive' | translate }}</p>
              }
            </div>
            @if (userHalt()) {
              <button type="button" (click)="onReleaseUser()"
                      class="px-3 py-2 rounded border border-gray-300 text-sm hover:bg-white">
                {{ 'risk.switch.release' | translate }}
              </button>
            } @else if (!userMfaOpen()) {
              <button type="button" (click)="openUserHalt()"
                      class="bg-red-600 text-white px-3 py-2 rounded text-sm hover:bg-red-700">
                {{ 'risk.switch.halt' | translate }}
              </button>
            }
          </div>

          <label class="mt-3 inline-flex items-center gap-2 text-sm">
            <input type="checkbox" [checked]="userFlatten()" (change)="toggleUserFlatten()" class="rounded" />
            {{ 'risk.switch.flatten' | translate }}
          </label>

          <!-- MFA prompt (open when arming the USER halt) -->
          @if (userMfaOpen()) {
            <form [formGroup]="mfaForm" (ngSubmit)="onConfirmHalt()"
                  class="mt-3 flex flex-wrap items-center gap-2">
              <span class="text-sm text-gray-600">{{ 'risk.mfa_prompt' | translate }}</span>
              <input type="text" inputmode="numeric" formControlName="mfa_code" maxlength="6"
                     autocomplete="one-time-code"
                     [placeholder]="'risk.switch.mfa_placeholder' | translate"
                     class="border rounded px-3 py-2 font-mono text-sm w-32" />
              <button type="submit" [disabled]="mfaForm.invalid"
                      class="bg-red-600 text-white px-3 py-2 rounded text-sm hover:bg-red-700 disabled:opacity-50">
                {{ 'risk.switch.confirm_halt' | translate }}
              </button>
              <button type="button" (click)="cancelUserHalt()"
                      class="px-3 py-2 rounded text-sm border hover:bg-gray-50">
                {{ 'common.cancel' | translate }}
              </button>
            </form>
          }

          @if (haltError(); as err) {
            <p class="mt-2 text-sm text-red-700">
              @if (knownError(err.code)) {
                {{ ('risk.error.' + err.code) | translate }}
              } @else {
                {{ err.message }}
              }
            </p>
          }
        </div>

        <!-- Other active switches (STRATEGY / PLATFORM) -->
        @if (otherHalts().length > 0) {
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            @for (ks of otherHalts(); track ks.id) {
              <div class="border rounded-lg p-4">
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <p class="font-medium">
                      {{ ('risk.switch.' + ks.scope) | translate }}
                      <span class="ml-1 text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700">L{{ ks.level }}</span>
                      @if (ks.auto) {
                        <span class="ml-1 text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800">
                          {{ 'risk.switch.auto' | translate }}
                        </span>
                      }
                    </p>
                    @if (ks.strategy) {
                      <p class="text-xs font-mono text-gray-500 break-all">{{ ks.strategy }}</p>
                    }
                    @if (ks.reason) {
                      <p class="text-sm text-gray-600">{{ ('risk.reason.' + ks.reason) | translate }}</p>
                    }
                    <p class="text-xs text-gray-400">{{ ks.created_at | date:'short' }}</p>
                  </div>
                  <button type="button" (click)="onReleaseOther(ks)"
                          class="px-3 py-1.5 rounded border text-sm hover:bg-gray-50 shrink-0">
                    {{ 'risk.switch.release' | translate }}
                  </button>
                </div>
                @if (rowErrors()[ks.id]; as err) {
                  <p class="mt-2 text-xs text-red-700">
                    @if (knownError(err.code)) {
                      {{ ('risk.error.' + err.code) | translate }}
                    } @else {
                      {{ err.message }}
                    }
                  </p>
                }
              </div>
            }
          </div>
        }
      </section>

      <!-- ========== (c) Risk events feed ========== -->
      <section class="border rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-3">{{ 'risk.events.title' | translate }}</h2>
        @if (facade.events().length === 0) {
          <p class="text-sm text-gray-500">{{ 'risk.events.empty' | translate }}</p>
        } @else {
          <ul class="divide-y border border-gray-200 rounded">
            @for (e of facade.events(); track e.id) {
              <li class="px-3 py-2 flex items-center gap-3 text-sm">
                <span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700 shrink-0">
                  {{ ('risk.event.' + e.type) | translate }}
                </span>
                <span class="text-xs text-gray-400 shrink-0">{{ e.created_at | date:'short' }}</span>
                <code class="text-xs text-gray-500 truncate">{{ e.details | json }}</code>
              </li>
            }
          </ul>
        }
      </section>

      <!-- ========== (d) Sizing decisions feed ========== -->
      <section class="border rounded-lg p-6">
        <h2 class="text-lg font-semibold mb-3">{{ 'risk.sizing.title' | translate }}</h2>
        @if (sizingRows().length === 0) {
          <p class="text-sm text-gray-500">{{ 'risk.sizing.empty' | translate }}</p>
        } @else {
          <table class="w-full border border-gray-200 text-sm">
            <thead class="bg-gray-50 text-left">
              <tr>
                <th class="px-3 py-2">{{ 'risk.sizing.col.time' | translate }}</th>
                <th class="px-3 py-2">{{ 'risk.sizing.col.symbol' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'risk.sizing.col.requested' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'risk.sizing.col.computed' | translate }}</th>
                <th class="px-3 py-2">{{ 'risk.sizing.col.result' | translate }}</th>
              </tr>
            </thead>
            <tbody>
              @for (d of sizingRows(); track d.id) {
                <tr class="border-t border-gray-100">
                  <td class="px-3 py-2 whitespace-nowrap text-gray-500">{{ d.created_at | date:'short' }}</td>
                  <td class="px-3 py-2 font-medium">{{ d.symbol }}</td>
                  <td class="px-3 py-2 text-right font-mono">{{ fmtQty(d.requested_qty) }}</td>
                  <td class="px-3 py-2 text-right font-mono">{{ fmtQty(d.computed_qty) }}</td>
                  <td class="px-3 py-2">
                    @if (d.result === 'OK') {
                      <span class="text-xs px-2 py-0.5 rounded bg-green-100 text-green-800">
                        {{ 'risk.sizing.ok' | translate }}
                      </span>
                    } @else {
                      <span class="text-xs px-2 py-0.5 rounded bg-red-100 text-red-800">
                        {{ 'risk.sizing.reject' | translate }}
                        @if (d.reject_reason) { — {{ ('risk.reason.' + d.reject_reason) | translate }} }
                      </span>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      </section>
    </div>
  `,
})
export class RiskComponent implements OnInit {
  facade = inject(RiskFacade);
  private fb = inject(FormBuilder);

  readonly numericFields = NUMERIC_FIELDS;
  readonly assetClasses = ASSET_CLASSES;

  fieldErrors = signal<Record<string, string[]>>({});
  savedToast = signal(false);

  // Kill switch UI state
  userFlatten = signal(false);
  userMfaOpen = signal(false);
  haltError = signal<ApiError | null>(null);
  rowErrors = signal<Record<number, ApiError>>({});

  readonly userHalt = computed(() => this.facade.killswitches().find(k => k.scope === 'USER') ?? null);
  readonly otherHalts = computed(() => this.facade.killswitches().filter(k => k.scope !== 'USER'));
  readonly sizingRows = computed(() => this.facade.sizingDecisions().slice(0, 50));

  profileForm = this.fb.nonNullable.group({
    risk_per_trade_pct: [0, Validators.required],
    max_position_pct: [0, Validators.required],
    max_concurrent: [0, Validators.required],
    daily_loss_usd: [0, Validators.required],
    daily_loss_pct: [0, Validators.required],
    leverage_cap: [0, Validators.required],
    soft_stop_pct: [0, Validators.required],
    hard_stop_pct: [0, Validators.required],
    atr_factor: [0, Validators.required],
    strict_mode: [false],
    permitted_asset_classes: [[] as string[]],
  });

  mfaForm = this.fb.nonNullable.group({
    mfa_code: ['', [Validators.required, Validators.minLength(6), Validators.maxLength(6)]],
  });

  async ngOnInit(): Promise<void> {
    await this.facade.loadProfile();
    this.patchForm();
    void this.facade.loadKillswitches();
    void this.facade.loadEvents();
    void this.facade.loadSizingDecisions();
  }

  // ---- Profile editor ----

  private patchForm(): void {
    const p = this.facade.profile();
    if (p) { this.profileForm.patchValue(p); }
  }

  hasClass(cls: string): boolean {
    return this.profileForm.controls.permitted_asset_classes.value.includes(cls);
  }

  toggleClass(cls: string): void {
    const current = this.profileForm.controls.permitted_asset_classes.value;
    const next = current.includes(cls) ? current.filter(c => c !== cls) : [...current, cls];
    this.profileForm.controls.permitted_asset_classes.setValue(next);
  }

  async onSave(): Promise<void> {
    if (this.profileForm.invalid) { return; }
    this.fieldErrors.set({});
    this.savedToast.set(false);
    const res = await this.facade.saveProfile(this.profileForm.getRawValue());
    if (res.ok) {
      this.savedToast.set(true);
    } else if (res.error.code === 'VALIDATION_ERROR' && res.error.details) {
      this.fieldErrors.set(res.error.details);
    } else {
      // Surface a single-field-less message via the general error block.
      this.fieldErrors.set({ non_field_errors: [res.error.message] });
    }
  }

  onDefaults(): void {
    this.fieldErrors.set({});
    this.savedToast.set(false);
    this.profileForm.reset(DEFAULTS);
  }

  /** Detail entries whose key doesn't map to a rendered field (shown as a block). */
  readonly generalErrors = computed(() => {
    const known = new Set<string>([
      ...NUMERIC_FIELDS.map(f => f.key),
      'strict_mode',
      'permitted_asset_classes',
    ]);
    const errs = this.fieldErrors();
    return Object.entries(errs)
      .filter(([key]) => !known.has(key))
      .flatMap(([, msgs]) => msgs);
  });

  // ---- Kill switches ----

  toggleUserFlatten(): void {
    this.userFlatten.set(!this.userFlatten());
  }

  openUserHalt(): void {
    this.haltError.set(null);
    this.mfaForm.reset();
    this.userMfaOpen.set(true);
  }

  cancelUserHalt(): void {
    this.userMfaOpen.set(false);
    this.mfaForm.reset();
  }

  async onConfirmHalt(): Promise<void> {
    if (this.mfaForm.invalid) { return; }
    this.haltError.set(null);
    const { mfa_code } = this.mfaForm.getRawValue();
    const res = await this.facade.triggerHalt('USER', { flatten: this.userFlatten(), mfa_code });
    if (res.ok) {
      this.userMfaOpen.set(false);
      this.mfaForm.reset();
    } else {
      // MFA_REQUIRED (wrong/expired code) — keep the prompt open and re-ask.
      this.haltError.set(res.error);
    }
  }

  async onReleaseUser(): Promise<void> {
    this.haltError.set(null);
    const res = await this.facade.releaseHalt('USER', { flatten: this.userFlatten() });
    if (!res.ok) {
      // e.g. 409 HALT_LOCKED when an L2 auto-halt blocks manual release.
      this.haltError.set(res.error);
    }
  }

  async onReleaseOther(ks: KillSwitch): Promise<void> {
    this._clearRowError(ks.id);
    const res = await this.facade.releaseHalt(ks.scope, { target_id: ks.strategy ?? undefined });
    if (!res.ok) {
      this._setRowError(ks.id, res.error);
    }
  }

  /** True when the code has a dedicated translated message under risk.error.*. */
  knownError(code: string): boolean {
    return KNOWN_ERRORS.has(code);
  }

  // ---- Formatting ----

  fmtQty(value: string): string {
    const n = Number(value);
    if (!isFinite(n)) { return value; }
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(n);
  }

  private _setRowError(id: number, err: ApiError): void {
    this.rowErrors.set({ ...this.rowErrors(), [id]: err });
  }

  private _clearRowError(id: number): void {
    const next = { ...this.rowErrors() };
    delete next[id];
    this.rowErrors.set(next);
  }
}
