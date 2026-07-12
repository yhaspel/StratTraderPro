/** /admin/users/:id — user detail with disable/enable + impersonate actions
 *  (each gated behind an inline MFA code + reason) and the recent audit trail.
 */
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ApiError } from '../../core/models/auth.models';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { TotpInputComponent } from '../auth/totp-input/totp-input.component';

type Action = 'disable' | 'enable' | 'impersonate';

@Component({
  selector: 'app-admin-user-detail',
  standalone: true,
  imports: [RouterLink, TranslateModule, DatePipe, ImpersonationBannerComponent, TotpInputComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-4xl p-6 space-y-6">
      <a routerLink="/admin/users" class="text-sm text-blue-600 hover:underline">{{ 'admin.nav.back_users' | translate }}</a>

      @if (admin.loading()) {
        <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
      }
      @if (!admin.loading() && admin.selectedUser(); as u) {
        <div class="flex items-start justify-between">
          <div>
            <h1 class="text-2xl font-bold">{{ u.display_name }}</h1>
            <p class="text-sm text-gray-500">{{ u.email }}</p>
          </div>
          <span class="text-sm px-2 py-1 rounded"
                [class.bg-green-100]="u.is_active" [class.text-green-700]="u.is_active"
                [class.bg-red-100]="!u.is_active" [class.text-red-700]="!u.is_active">
            {{ (u.is_active ? 'admin.detail.active' : 'admin.detail.disabled') | translate }}
          </span>
        </div>

        <!-- ===== Fields ===== -->
        <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm border rounded p-4">
          <dt class="text-gray-500">{{ 'admin.detail.verified' | translate }}</dt>
          <dd>{{ (u.is_verified ? 'admin.users.filter.active_yes' : 'admin.users.filter.active_no') | translate }}</dd>
          <dt class="text-gray-500">{{ 'admin.detail.mfa' | translate }}</dt>
          <dd>{{ (u.mfa_enabled ? 'admin.users.on' : 'admin.users.off') | translate }}</dd>
          <dt class="text-gray-500">{{ 'admin.detail.staff' | translate }}</dt>
          <dd>{{ (u.is_staff ? 'admin.users.filter.active_yes' : 'admin.users.filter.active_no') | translate }}</dd>
          <dt class="text-gray-500">{{ 'admin.detail.created' | translate }}</dt>
          <dd>{{ u.created_at | date:'medium' }}</dd>
        </dl>

        <!-- ===== Brokers ===== -->
        <section>
          <h2 class="text-lg font-semibold mb-2">{{ 'admin.detail.brokers' | translate }}</h2>
          @if (u.brokers.length === 0) {
            <p class="text-sm text-gray-500">{{ 'admin.detail.no_brokers' | translate }}</p>
          } @else {
            <ul class="divide-y border rounded text-sm">
              @for (b of u.brokers; track b.id) {
                <li class="px-3 py-2 flex items-center justify-between">
                  <span class="font-medium">{{ b.broker }} · {{ b.mode }}</span>
                  <span class="text-gray-500">{{ b.account_number || '—' }}</span>
                  <span [class.text-green-700]="b.status === 'CONNECTED'">{{ b.status }}</span>
                  @if (b.is_default) { <span class="text-xs text-blue-600">{{ 'admin.detail.default' | translate }}</span> }
                </li>
              }
            </ul>
          }
        </section>

        <!-- ===== Actions ===== -->
        <section class="border rounded p-4 space-y-3">
          <h2 class="text-lg font-semibold">{{ 'admin.detail.actions' | translate }}</h2>
          <div class="flex flex-wrap gap-3">
            @if (u.is_active) {
              <button type="button" (click)="open('disable')"
                      class="bg-red-600 text-white text-sm px-4 py-2 rounded hover:bg-red-700">
                {{ 'admin.detail.disable' | translate }}
              </button>
            } @else {
              <button type="button" (click)="open('enable')"
                      class="bg-green-600 text-white text-sm px-4 py-2 rounded hover:bg-green-700">
                {{ 'admin.detail.enable' | translate }}
              </button>
            }
            <button type="button" (click)="open('impersonate')" [disabled]="admin.isImpersonating()"
                    class="bg-amber-500 text-black text-sm px-4 py-2 rounded hover:bg-amber-600 disabled:opacity-40">
              {{ 'admin.detail.impersonate' | translate }}
            </button>
          </div>

          <!-- Inline MFA + reason prompt -->
          @if (action(); as act) {
            <div class="border-t pt-3 space-y-3">
              <p class="text-sm font-medium">{{ ('admin.detail.confirm.' + act) | translate }}</p>
              <div>
                <label for="admin-action-reason" class="block text-xs font-semibold text-gray-700 uppercase mb-1">
                  {{ 'admin.detail.reason' | translate }}
                </label>
                <input id="admin-action-reason" type="text" [value]="reason()"
                       (input)="reason.set($any($event.target).value)" autocomplete="off"
                       class="w-full text-sm border rounded px-3 py-2" />
              </div>
              <span class="block text-xs font-semibold text-gray-700 uppercase">{{ 'admin.detail.mfa' | translate }}</span>
              <app-totp-input [ariaLabel]="'MFA code'" (codeChange)="mfaCode.set($event)" [disabled]="submitting()" />
              @if (actionError(); as err) {
                <p class="text-sm text-red-700">
                  @if (err.code === 'MFA_REQUIRED') {
                    {{ 'admin.detail.error.MFA_REQUIRED' | translate }}
                  } @else {
                    {{ err.message }}
                  }
                </p>
              }
              <div class="flex gap-3 justify-end">
                <button type="button" (click)="cancel()" class="px-3 py-1 rounded border text-sm hover:bg-gray-50">
                  {{ 'common.cancel' | translate }}
                </button>
                <button type="button" (click)="submit(u.id)" [disabled]="mfaCode().length !== 6 || submitting()"
                        class="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700 disabled:opacity-40">
                  {{ (submitting() ? 'admin.detail.submitting' : 'common.confirm') | translate }}
                </button>
              </div>
            </div>
          }
        </section>

        <!-- ===== Recent audit ===== -->
        <section>
          <h2 class="text-lg font-semibold mb-2">{{ 'admin.detail.recent_audit' | translate }}</h2>
          @if (u.recent_audit.length === 0) {
            <p class="text-sm text-gray-500">{{ 'admin.detail.no_audit' | translate }}</p>
          } @else {
            <ul class="divide-y border rounded text-sm">
              @for (a of u.recent_audit; track a.id) {
                <li class="px-3 py-2 flex items-center justify-between">
                  <span class="font-medium">{{ eventLabel(a.event_type) }}</span>
                  <span class="text-xs text-gray-400">{{ a.occurred_at | date:'short' }}</span>
                </li>
              }
            </ul>
          }
        </section>
      }
      @if (!admin.loading() && !admin.selectedUser() && admin.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">{{ err.message }}</div>
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
