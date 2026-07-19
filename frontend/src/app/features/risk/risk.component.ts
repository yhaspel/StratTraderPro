/** /risk — risk envelope editor, kill switches, and audit feeds (M08).
 *
 * Four sections ("Industry" design system):
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
import { BlueprintDirective } from '../shared/ui/blueprint.directive';
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { ChipTone, StatusChipComponent } from '../shared/ui/status-chip.component';

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

/** Risk-event type → chip tone (notes §3: warn/down are the working tones). */
const EVENT_TONES: Record<string, ChipTone> = {
  DAILY_LOSS_BREACH: 'down',
  KILL_SWITCH_ON: 'down',
  KILL_SWITCH_OFF: 'up',
  SOFT_STOP: 'warn',
  SIZING_REJECT: 'down',
  FLATTEN: 'warn',
};

@Component({
  selector: 'app-risk',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    TranslateModule,
    DatePipe,
    BlueprintDirective,
    ButtonComponent,
    CardComponent,
    PageHeaderComponent,
    StatusChipComponent,
  ],
  template: `
    <div class="mx-auto max-w-5xl p-6">
      <app-page-header [heading]="'risk.title' | translate" />

      <div class="grid items-start gap-s6 lg:grid-cols-2">
        <!-- ========== (a) Profile editor ========== -->
        <app-card>
          <h2 class="m-0 mb-s3 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
            {{ 'risk.profile.title' | translate }}
          </h2>

          @if (facade.loading() && !facade.profile()) {
            <p class="text-sm text-neutral-600">{{ 'common.loading' | translate }}</p>
          } @else {
            <form [formGroup]="profileForm" (ngSubmit)="onSave()" class="space-y-s4">
              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                @for (f of numericFields; track f.key) {
                  <div>
                    <label class="mb-1 block text-xs font-medium text-neutral-600" [attr.for]="f.key">
                      {{ ('risk.profile.' + f.key) | translate }}
                    </label>
                    <input type="number" [id]="f.key" [formControlName]="f.key" [step]="f.step"
                           class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-accent focus:outline-none" />
                    <p class="mt-1 text-[11px] text-neutral-600">{{ ('risk.profile.' + f.key + '_help') | translate }}</p>
                    @if (fieldErrors()[f.key]; as errs) {
                      <p class="mt-1 text-xs text-down-deep">{{ errs.join(' ') }}</p>
                    }
                  </div>
                }
              </div>

              <!-- strict_mode -->
              <div>
                <label class="inline-flex items-center gap-2 text-sm font-medium text-ink">
                  <input type="checkbox" formControlName="strict_mode"
                         class="h-[15px] w-[15px] rounded-none accent-accent" />
                  {{ 'risk.profile.strict_mode' | translate }}
                </label>
                <p class="mt-1 text-[11px] text-neutral-600">{{ 'risk.profile.strict_mode_help' | translate }}</p>
              </div>

              <!-- permitted_asset_classes multi-select -->
              <div>
                <span class="mb-1 block text-xs font-medium text-neutral-600">{{ 'risk.profile.permitted_asset_classes' | translate }}</span>
                <div class="flex flex-wrap gap-2">
                  @for (cls of assetClasses; track cls) {
                    <label class="inline-flex cursor-pointer items-center gap-1.5 rounded-none border px-3 py-1.5 text-sm"
                           [class.border-accent]="hasClass(cls)"
                           [class.bg-accent-100]="hasClass(cls)"
                           [class.text-accent-800]="hasClass(cls)"
                           [class.border-divider]="!hasClass(cls)"
                           [class.text-ink]="!hasClass(cls)">
                      <input type="checkbox" [checked]="hasClass(cls)" (change)="toggleClass(cls)"
                             class="h-[13px] w-[13px] rounded-none accent-accent" />
                      {{ ('risk.profile.asset_class.' + cls) | translate }}
                    </label>
                  }
                </div>
                @if (fieldErrors()['permitted_asset_classes']; as errs) {
                  <p class="mt-1 text-xs text-down-deep">{{ errs.join(' ') }}</p>
                }
              </div>

              <!-- Non-field / cross-field validation errors (e.g. soft/hard stop) -->
              @if (generalErrors().length > 0) {
                <div class="rounded-none border border-down bg-down-tint px-3 py-2 text-sm text-down-deep" role="alert">
                  @for (msg of generalErrors(); track msg) {
                    <p>{{ msg }}</p>
                  }
                </div>
              }

              @if (savedToast()) {
                <p class="text-sm text-accent-700">✓ {{ 'risk.profile.saved' | translate }}</p>
              }

              <div class="flex gap-2.5">
                <app-button type="submit" variant="primary" [disabled]="profileForm.invalid">
                  {{ 'risk.save' | translate }}
                </app-button>
                <app-button variant="secondary" (clicked)="onDefaults()">
                  {{ 'risk.defaults' | translate }}
                </app-button>
              </div>
            </form>
          }
        </app-card>

        <div class="flex flex-col gap-s6">
          <!-- ========== (b) Active kill switches ========== -->
          <!-- Red border treatment (Industry, notes §3: kill switch active → down)
               via [style.borderColor]: the global .blueprint rule sets the hairline
               after the Tailwind utilities layer, so a border-* class can't win. -->
          <section stpBlueprint class="p-s4"
                   [style.borderColor]="userHalt() ? 'var(--down)' : null"
                   [class.bg-down-tint]="!!userHalt()">
            <h2 class="m-0 mb-s3 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
              {{ 'risk.switch.title' | translate }}
            </h2>

            <!-- Personal (L1 / USER) halt row -->
            <div class="flex items-start justify-between gap-3.5">
              <div>
                <p class="text-sm font-bold text-ink">
                  {{ 'risk.switch.USER' | translate }}
                  @if (userHalt(); as ks) {
                    <span class="ml-1 font-mono text-[10px] font-normal text-neutral-600">{{ ks.level }} / {{ ks.scope }}</span>
                  }
                </p>
                @if (userHalt(); as ks) {
                  <p class="mt-0.5 text-sm text-down">
                    {{ 'risk.switch.active' | translate }} ·
                    {{ 'risk.switch.since' | translate }} <span class="font-mono">{{ ks.created_at | date:'short' }}</span>
                    @if (ks.reason) { · {{ ('risk.reason.' + ks.reason) | translate }} }
                  </p>
                } @else {
                  <p class="mt-0.5 text-sm text-neutral-600">{{ 'risk.switch.inactive' | translate }}</p>
                }
              </div>
              @if (userHalt(); as ks) {
                @if (ks.auto) {
                  <app-status-chip tone="warn" class="shrink-0">
                    {{ 'risk.switch.auto_locked' | translate }}
                  </app-status-chip>
                } @else {
                  <app-button variant="success" (clicked)="onReleaseUser()">
                    {{ 'risk.switch.release' | translate }}
                  </app-button>
                }
              } @else if (!userMfaOpen()) {
                <app-button variant="danger" (clicked)="openUserHalt()">
                  {{ 'risk.switch.halt' | translate }}
                </app-button>
              }
            </div>

            <label class="mt-s3 inline-flex items-center gap-2 text-sm text-neutral-600">
              <input type="checkbox" [checked]="userFlatten()" (change)="toggleUserFlatten()"
                     class="h-[15px] w-[15px] rounded-none accent-accent" />
              {{ 'risk.switch.flatten' | translate }}
            </label>

            <!-- MFA prompt (open when arming the USER halt) — the one inline
                 MFA confirm pattern: input → danger confirm → secondary cancel -->
            @if (userMfaOpen()) {
              <form [formGroup]="mfaForm" (ngSubmit)="onConfirmHalt()"
                    class="mt-s3 flex flex-wrap items-center gap-2 border-t border-divider pt-s3">
                <span class="text-sm text-neutral-600">{{ 'risk.mfa_prompt' | translate }}</span>
                <input type="text" inputmode="numeric" formControlName="mfa_code" maxlength="6"
                       autocomplete="one-time-code"
                       [placeholder]="'risk.switch.mfa_placeholder' | translate"
                       class="w-32 rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-accent focus:outline-none" />
                <app-button type="submit" variant="danger" [disabled]="mfaForm.invalid">
                  {{ 'risk.switch.confirm_halt' | translate }}
                </app-button>
                <app-button variant="secondary" (clicked)="cancelUserHalt()">
                  {{ 'common.cancel' | translate }}
                </app-button>
              </form>
            }

            @if (haltError(); as err) {
              <p class="mt-2 text-sm text-down-deep">
                @if (knownError(err.code)) {
                  {{ ('risk.error.' + err.code) | translate }}
                } @else {
                  {{ err.message }}
                }
              </p>
            }

            <!-- Other active switches (STRATEGY / PLATFORM) -->
            @for (ks of otherHalts(); track ks.id) {
              <div class="mt-s3 border-t border-divider pt-s3">
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <p class="text-sm font-bold text-ink">
                      {{ ('risk.switch.' + ks.scope) | translate }}
                      <span class="ml-1 font-mono text-[10px] font-normal text-neutral-600">{{ ks.level }}</span>
                      @if (ks.auto) {
                        <app-status-chip status="AUTO" class="ml-1">
                          {{ 'risk.switch.auto' | translate }}
                        </app-status-chip>
                      }
                    </p>
                    @if (ks.strategy) {
                      <p class="break-all font-mono text-[11px] text-neutral-600">{{ ks.strategy }}</p>
                    }
                    @if (ks.reason) {
                      <p class="text-sm text-neutral-600">{{ ('risk.reason.' + ks.reason) | translate }}</p>
                    }
                    <p class="font-mono text-xs text-neutral-600">{{ ks.created_at | date:'short' }}</p>
                  </div>
                  <app-button variant="success" class="shrink-0" (clicked)="onReleaseOther(ks)">
                    {{ 'risk.switch.release' | translate }}
                  </app-button>
                </div>
                @if (rowErrors()[ks.id]; as err) {
                  <p class="mt-2 text-xs text-down-deep">
                    @if (knownError(err.code)) {
                      {{ ('risk.error.' + err.code) | translate }}
                    } @else {
                      {{ err.message }}
                    }
                  </p>
                }
              </div>
            }
          </section>

          <!-- ========== (c) Risk events feed ========== -->
          <app-card>
            <h2 class="m-0 mb-s2 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
              {{ 'risk.events.title' | translate }}
            </h2>
            @if (facade.events().length === 0) {
              <p class="text-sm text-neutral-600">{{ 'risk.events.empty' | translate }}</p>
            } @else {
              <ul class="divide-y divide-divider">
                @for (e of facade.events(); track e.id) {
                  <li class="flex items-center gap-2.5 py-1.5 text-xs">
                    <app-status-chip [tone]="eventTone(e.type)" class="shrink-0">
                      {{ ('risk.event.' + e.type) | translate }}
                    </app-status-chip>
                    <span class="shrink-0 font-mono text-xs text-neutral-600">{{ e.created_at | date:'short' }}</span>
                    <code class="min-w-0 truncate font-mono text-xs text-neutral-600">{{ e.details | json }}</code>
                  </li>
                }
              </ul>
            }
          </app-card>
        </div>
      </div>

      <!-- ========== (d) Sizing decisions feed ========== -->
      <div class="mt-s6">
        <app-card>
          <h2 class="m-0 mb-s2 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
            {{ 'risk.sizing.title' | translate }}
          </h2>
          @if (sizingRows().length === 0) {
            <p class="text-sm text-neutral-600">{{ 'risk.sizing.empty' | translate }}</p>
          } @else {
            <table class="w-full text-[13px]">
              <thead class="text-left">
                <tr>
                  <th class="border-b border-divider px-3 py-2 font-heading font-semibold text-[11px] uppercase tracking-[0.08em] text-neutral-600">{{ 'risk.sizing.col.time' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 font-heading font-semibold text-[11px] uppercase tracking-[0.08em] text-neutral-600">{{ 'risk.sizing.col.symbol' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-right font-heading font-semibold text-[11px] uppercase tracking-[0.08em] text-neutral-600">{{ 'risk.sizing.col.requested' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 text-right font-heading font-semibold text-[11px] uppercase tracking-[0.08em] text-neutral-600">{{ 'risk.sizing.col.computed' | translate }}</th>
                  <th class="border-b border-divider px-3 py-2 font-heading font-semibold text-[11px] uppercase tracking-[0.08em] text-neutral-600">{{ 'risk.sizing.col.result' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (d of sizingRows(); track d.id) {
                  <tr class="border-t border-divider">
                    <td class="whitespace-nowrap px-3 py-1.5 font-mono text-xs text-neutral-600">{{ d.created_at | date:'short' }}</td>
                    <td class="px-3 py-1.5 font-bold text-ink">{{ d.symbol }}</td>
                    <td class="px-3 py-1.5 text-right font-mono">{{ fmtQty(d.requested_qty) }}</td>
                    <td class="px-3 py-1.5 text-right font-mono">{{ fmtQty(d.computed_qty) }}</td>
                    <td class="px-3 py-1.5">
                      @if (d.result === 'OK') {
                        <app-status-chip tone="up">{{ 'risk.sizing.ok' | translate }}</app-status-chip>
                      } @else {
                        <app-status-chip tone="down">
                          {{ 'risk.sizing.reject' | translate }}
                          @if (d.reject_reason) { — {{ ('risk.reason.' + d.reject_reason) | translate }} }
                        </app-status-chip>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          }
        </app-card>
      </div>
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

  /** Chip tone for a risk-event type (unknown types stay neutral). */
  eventTone(type: string): ChipTone {
    return EVENT_TONES[type] ?? 'neutral';
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
