/**
 * /settings/data-providers — instance FMP + FRED API keys (ADR-062).
 *
 * One set of keys per instance, staff-editable, stored encrypted server-side.
 * A key saved here takes effect on every service (web, worker, beat)
 * immediately and overrides the FMP_API_KEY / FRED_API_KEY env vars; removing
 * it falls back to the env var, if one is set. Keys are write-only: the form
 * sends them up and the API never echoes them back (only a last-4 hint).
 */
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { ApiError } from '../../../core/models/auth.models';
import {
  DataProvider,
  ProviderKeyStatus,
} from '../../../core/models/data-providers.models';
import { DataProvidersFacade } from '../../../abstraction/facades/data-providers.facade';
import { AuthStore } from '../../../abstraction/stores/auth.store';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { StatusChipComponent } from '../../shared/ui/status-chip.component';

/** Error codes that have a dedicated translated message. */
const KNOWN_ERRORS = new Set([
  'INVALID_API_KEY',
  'PROVIDER_UNREACHABLE',
  'UNKNOWN_PROVIDER',
  'VALIDATION_ERROR',
  'FORBIDDEN',
  'MFA_REQUIRED',
]);

interface ProviderView {
  id: DataProvider;
  wire: 'fmp' | 'fred';
  ns: string;
  docsUrl: string;
}

@Component({
  selector: 'app-data-providers',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
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
      <app-page-header [heading]="'data_providers.title' | translate" />

      <div class="flex flex-col gap-s6">
        <!-- ========== What these keys power ========== -->
        <app-card>
          <p class="m-0 text-sm text-neutral-700">{{ 'data_providers.intro' | translate }}</p>
          <a routerLink="/guides/market-regime-setup"
             class="mt-2 inline-block text-[13px] text-accent-700 underline">
            {{ 'data_providers.guide_link' | translate }}
          </a>
          @if (!isStaff()) {
            <p class="mt-3 text-sm text-neutral-700">{{ 'data_providers.staff_only' | translate }}</p>
          }
        </app-card>

        <!-- Page-level load error (e.g. MFA not enrolled yet). -->
        @if (facade.error(); as err) {
          <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
            @if (err.code === 'MFA_REQUIRED') {
              {{ 'data_providers.error.MFA_REQUIRED' | translate }}
              <a routerLink="/settings/security" class="underline">{{ 'data_providers.mfa_link' | translate }}</a>
            } @else if (knownError(err.code)) {
              {{ ('data_providers.error.' + err.code) | translate }}
            } @else {
              {{ err.message }}
            }
          </div>
        }

        <!-- ========== One card per provider ========== -->
        @for (p of providers; track p.id) {
          <app-card>
            <div class="mb-s3 flex items-start justify-between gap-3">
              <div>
                <h2 class="m-0 font-heading font-semibold text-[13px] uppercase tracking-[0.1em] text-neutral-700">
                  {{ (p.ns + '.title') | translate }}
                </h2>
                <p class="mt-0.5 text-sm text-neutral-700">
                  {{ (p.ns + '.subtitle') | translate }}
                  <a [href]="p.docsUrl" target="_blank" rel="noopener noreferrer"
                     class="text-accent-700 hover:underline">{{ (p.ns + '.get_key') | translate }}</a>
                </p>
              </div>
              @if (statusFor(p.wire); as s) {
                @if (s.configured) {
                  <app-status-chip tone="up" [dot]="true" class="shrink-0">
                    {{ (s.source === 'env' ? 'data_providers.status.configured_env'
                                           : 'data_providers.status.configured_ui') | translate }}
                  </app-status-chip>
                } @else {
                  <app-status-chip tone="neutral" class="shrink-0">
                    {{ 'data_providers.status.not_configured' | translate }}
                  </app-status-chip>
                }
              } @else if (facade.loading()) {
                <span class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</span>
              }
            </div>

            @if (statusFor(p.wire); as s) {
              <!-- Staff-only detail line for a UI-stored key. -->
              @if (s.source === 'ui' && s.hint) {
                <p class="mb-s3 font-mono text-xs text-neutral-700">
                  {{ 'data_providers.hint_label' | translate }} …{{ s.hint }}
                  @if (s.updated_by) {
                    · {{ 'data_providers.updated_by' | translate }} {{ s.updated_by }}
                  }
                  @if (s.updated_at) {
                    · {{ s.updated_at | date:'medium' }}
                  }
                </p>
              }
              <!-- Explain precedence when the env var is the current source. -->
              @if (s.source === 'env' && isStaff()) {
                <p class="mb-s3 text-xs text-neutral-700">{{ 'data_providers.env_active_note' | translate }}</p>
              }

              @if (isStaff()) {
                <form [formGroup]="form(p.id)" (ngSubmit)="onSave(p.id)" class="max-w-md space-y-3">
                  <div>
                    <label class="mb-1 block text-xs font-medium text-neutral-700" [for]="'key-' + p.wire">
                      {{ 'data_providers.form.api_key' | translate }}
                    </label>
                    <input [id]="'key-' + p.wire" type="password" formControlName="api_key"
                           autocomplete="new-password"
                           class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-accent focus:outline-none" />
                  </div>
                  <div class="flex flex-wrap items-center gap-2">
                    <app-button type="submit" variant="primary"
                                [disabled]="form(p.id).invalid || facade.loading()">
                      {{ (s.source === 'ui' ? 'data_providers.form.replace' : 'data_providers.form.save') | translate }}
                    </app-button>
                    @if (s.source === 'ui' && removing() !== p.id) {
                      <app-button variant="ghost" (clicked)="startRemove(p.id)">
                        <span class="text-down">{{ 'data_providers.form.remove' | translate }}</span>
                      </app-button>
                    }
                  </div>
                </form>

                <!-- Inline remove confirm (house pattern: danger confirm + cancel). -->
                @if (removing() === p.id) {
                  <div class="mt-s3 flex flex-wrap items-center gap-2 border-t border-divider pt-s3">
                    <span class="text-sm text-neutral-700">{{ 'data_providers.form.env_note' | translate }}</span>
                    <app-button variant="danger" (clicked)="confirmRemove(p.id)">
                      {{ 'data_providers.form.confirm_remove' | translate }}
                    </app-button>
                    <app-button variant="secondary" (clicked)="cancelRemove()">
                      {{ 'common.cancel' | translate }}
                    </app-button>
                  </div>
                }
              }

              <!-- Per-card outcome -->
              @if (successes()[p.id]; as done) {
                <p class="mt-3 text-sm text-accent-700" role="status">
                  ✓ {{ (done === 'saved' ? 'data_providers.form.saved' : 'data_providers.form.removed') | translate }}
                </p>
              }
              @if (errors()[p.id]; as err) {
                <p class="mt-3 text-sm text-down-deep" role="alert">
                  @if (knownError(err.code)) {
                    {{ ('data_providers.error.' + err.code) | translate }}
                  } @else {
                    {{ err.message }}
                  }
                </p>
              }
            }
          </app-card>
        }
      </div>
    </div>
  `,
})
export class DataProvidersComponent implements OnInit {
  facade = inject(DataProvidersFacade);
  private fb = inject(FormBuilder);
  private store = inject(AuthStore);

  isStaff = computed(() => this.store.user()?.is_staff === true);

  readonly providers: ProviderView[] = [
    {
      id: 'FMP',
      wire: 'fmp',
      ns: 'data_providers.fmp',
      docsUrl: 'https://site.financialmodelingprep.com/developer/docs',
    },
    {
      id: 'FRED',
      wire: 'fred',
      ns: 'data_providers.fred',
      docsUrl: 'https://fred.stlouisfed.org/docs/api/api_key.html',
    },
  ];

  private forms = {
    FMP: this.fb.nonNullable.group({ api_key: ['', Validators.required] }),
    FRED: this.fb.nonNullable.group({ api_key: ['', Validators.required] }),
  };

  successes = signal<Partial<Record<DataProvider, 'saved' | 'removed'>>>({});
  errors = signal<Partial<Record<DataProvider, ApiError>>>({});
  removing = signal<DataProvider | null>(null);

  ngOnInit(): void {
    void this.facade.load();
  }

  form(p: DataProvider) {
    return this.forms[p];
  }

  statusFor(wire: 'fmp' | 'fred'): ProviderKeyStatus | undefined {
    return this.facade.keys()?.[wire];
  }

  async onSave(p: DataProvider): Promise<void> {
    if (this.form(p).invalid) { return; }
    this._clearOutcome(p);
    const { api_key } = this.form(p).getRawValue();
    const res = await this.facade.set(p, api_key);
    if (res.ok) {
      this.form(p).reset(); // wipes the key from memory
      this.successes.set({ ...this.successes(), [p]: 'saved' });
    } else {
      this.errors.set({ ...this.errors(), [p]: res.error });
    }
  }

  startRemove(p: DataProvider): void {
    this._clearOutcome(p);
    this.removing.set(p);
  }

  cancelRemove(): void {
    this.removing.set(null);
  }

  async confirmRemove(p: DataProvider): Promise<void> {
    this.removing.set(null);
    const res = await this.facade.remove(p);
    if (res.ok) {
      this.successes.set({ ...this.successes(), [p]: 'removed' });
    } else {
      this.errors.set({ ...this.errors(), [p]: res.error });
    }
  }

  knownError(code: string): boolean {
    return KNOWN_ERRORS.has(code);
  }

  private _clearOutcome(p: DataProvider): void {
    const s = { ...this.successes() };
    const e = { ...this.errors() };
    delete s[p];
    delete e[p];
    this.successes.set(s);
    this.errors.set(e);
  }
}
