/** /admin/users/:id — user detail with disable/enable + impersonate actions
 *  (each gated behind an inline MFA code + reason) and the recent audit trail.
 *  Industry styling: page header + status chip, blueprint cards, shared
 *  inline-confirm grammar (input → confirm → secondary cancel).
 */
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

type Action = 'disable' | 'enable' | 'impersonate';

@Component({
  selector: 'app-admin-user-detail',
  standalone: true,
  imports: [
    RouterLink, TranslateModule, DatePipe, ImpersonationBannerComponent, TotpInputComponent,
    ButtonComponent, CardComponent, PageHeaderComponent, StatusChipComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-4xl space-y-6 p-6">
      <a routerLink="/admin/users" class="text-sm text-accent-700 hover:underline">{{ 'admin.nav.back_users' | translate }}</a>

      @if (admin.loading()) {
        <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
      }
      @if (!admin.loading() && admin.selectedUser(); as u) {
        <app-page-header [heading]="u.display_name" [subtitle]="u.email">
          <span actions>
            <app-status-chip [tone]="u.is_active ? 'up' : 'down'">
              {{ (u.is_active ? 'admin.detail.active' : 'admin.detail.disabled') | translate }}
            </app-status-chip>
          </span>
        </app-page-header>

        <!-- ===== Fields ===== -->
        <app-card>
          <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt class="text-neutral-700">{{ 'admin.detail.verified' | translate }}</dt>
            <dd>{{ (u.is_verified ? 'admin.users.filter.active_yes' : 'admin.users.filter.active_no') | translate }}</dd>
            <dt class="text-neutral-700">{{ 'admin.detail.mfa' | translate }}</dt>
            <dd>{{ (u.mfa_enabled ? 'admin.users.on' : 'admin.users.off') | translate }}</dd>
            <dt class="text-neutral-700">{{ 'admin.detail.staff' | translate }}</dt>
            <dd>{{ (u.is_staff ? 'admin.users.filter.active_yes' : 'admin.users.filter.active_no') | translate }}</dd>
            <dt class="text-neutral-700">{{ 'admin.detail.created' | translate }}</dt>
            <dd>{{ u.created_at | date:'medium' }}</dd>
          </dl>
        </app-card>

        <!-- ===== Brokers ===== -->
        <section>
          <h2 class="mb-2 font-heading text-lg font-semibold text-ink">{{ 'admin.detail.brokers' | translate }}</h2>
          @if (u.brokers.length === 0) {
            <p class="text-sm text-neutral-700">{{ 'admin.detail.no_brokers' | translate }}</p>
          } @else {
            <app-card>
              <ul class="divide-y divide-divider text-[13px]">
                @for (b of u.brokers; track b.id) {
                  <li class="flex items-center justify-between gap-3 px-3 py-2">
                    <span class="font-medium">{{ b.broker }} · {{ b.mode }}</span>
                    <span class="font-mono tabular-nums text-neutral-700">{{ b.account_number || '—' }}</span>
                    <app-status-chip [status]="b.status" [dot]="true">{{ b.status }}</app-status-chip>
                    @if (b.is_default) {
                      <app-status-chip tone="outline">{{ 'admin.detail.default' | translate }}</app-status-chip>
                    }
                  </li>
                }
              </ul>
            </app-card>
          }
        </section>

        <!-- ===== Actions ===== -->
        <app-card>
          <div class="space-y-3">
            <h2 class="font-heading text-lg font-semibold text-ink">{{ 'admin.detail.actions' | translate }}</h2>
            <div class="flex flex-wrap gap-3">
              @if (u.is_active) {
                <app-button variant="danger" (clicked)="open('disable')">
                  {{ 'admin.detail.disable' | translate }}
                </app-button>
              } @else {
                <app-button variant="primary" (clicked)="open('enable')">
                  {{ 'admin.detail.enable' | translate }}
                </app-button>
              }
              <app-button variant="secondary" (clicked)="open('impersonate')" [disabled]="admin.isImpersonating()">
                {{ 'admin.detail.impersonate' | translate }}
              </app-button>
            </div>

            <!-- Inline MFA + reason prompt -->
            @if (action(); as act) {
              <div class="space-y-3 border-t border-divider pt-3">
                <p class="text-sm font-medium">{{ ('admin.detail.confirm.' + act) | translate }}</p>
                <div>
                  <label for="admin-action-reason" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-700">
                    {{ 'admin.detail.reason' | translate }}
                  </label>
                  <input id="admin-action-reason" type="text" [value]="reason()"
                         (input)="reason.set($any($event.target).value)" autocomplete="off"
                         class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
                </div>
                <span class="block text-[11px] font-semibold uppercase tracking-wide text-accent-700">{{ 'admin.detail.mfa' | translate }}</span>
                <app-totp-input [ariaLabel]="'MFA code'" (codeChange)="mfaCode.set($event)" [disabled]="submitting()" />
                @if (actionError(); as err) {
                  <p class="text-sm text-down">
                    @if (err.code === 'MFA_REQUIRED') {
                      {{ 'admin.detail.error.MFA_REQUIRED' | translate }}
                    } @else {
                      {{ err.message }}
                    }
                  </p>
                }
                <div class="flex justify-end gap-3">
                  <app-button variant="primary" (clicked)="submit(u.id)"
                              [disabled]="mfaCode().length !== 6 || submitting()" [loading]="submitting()">
                    {{ (submitting() ? 'admin.detail.submitting' : 'common.confirm') | translate }}
                  </app-button>
                  <app-button variant="secondary" (clicked)="cancel()">
                    {{ 'common.cancel' | translate }}
                  </app-button>
                </div>
              </div>
            }
          </div>
        </app-card>

        <!-- ===== Recent audit ===== -->
        <section>
          <h2 class="mb-2 font-heading text-lg font-semibold text-ink">{{ 'admin.detail.recent_audit' | translate }}</h2>
          @if (u.recent_audit.length === 0) {
            <p class="text-sm text-neutral-700">{{ 'admin.detail.no_audit' | translate }}</p>
          } @else {
            <app-card>
              <ul class="divide-y divide-divider text-[13px]">
                @for (a of u.recent_audit; track a.id) {
                  <li class="flex items-center justify-between px-3 py-2">
                    <span class="font-medium">{{ eventLabel(a.event_type) }}</span>
                    <span class="text-xs text-neutral-700">{{ a.occurred_at | date:'short' }}</span>
                  </li>
                }
              </ul>
            </app-card>
          }
        </section>
      }
      @if (!admin.loading() && !admin.selectedUser() && admin.error(); as err) {
        <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">{{ err.message }}</div>
      }
    </div>
  `,
})
export class AdminUserDetailComponent implements OnInit {
  admin = inject(AdminFacade);
  private route = inject(ActivatedRoute);
  private translate = inject(TranslateService);

  action = signal<Action | null>(null);
  reason = signal('');
  mfaCode = signal('');
  submitting = signal(false);
  actionError = signal<ApiError | null>(null);

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) { void this.admin.openUser(id); }
  }

  eventLabel(type: string): string {
    const key = `audit.event.${type}`;
    const label = this.translate.instant(key);
    return label === key ? type : label;
  }

  open(action: Action): void {
    this.action.set(action);
    this.reason.set('');
    this.mfaCode.set('');
    this.actionError.set(null);
  }

  cancel(): void {
    this.action.set(null);
  }

  async submit(id: string): Promise<void> {
    const act = this.action();
    if (!act || this.mfaCode().length !== 6) { return; }
    this.actionError.set(null);
    this.submitting.set(true);
    const body = { mfa_code: this.mfaCode(), reason: this.reason() };
    try {
      const res =
        act === 'disable' ? await this.admin.disableUser(id, body)
        : act === 'enable' ? await this.admin.enableUser(id, body)
        : await this.admin.startImpersonation(id, body);
      if (res.ok) {
        this.action.set(null);
      } else {
        this.actionError.set(res.error);
      }
    } finally {
      this.submitting.set(false);
    }
  }
}
