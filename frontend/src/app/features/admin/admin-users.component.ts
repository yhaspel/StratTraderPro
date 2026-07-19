/** /admin/users — searchable, filterable, paginated user table (M10).
 * Industry styling: sub-nav with accent underline, dense blueprint table
 * (11px uppercase th, 13px rows, mono right-aligned counts), status chips. */
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { AdminUserListParams } from '../../core/models/admin.models';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

@Component({
  selector: 'app-admin-users',
  standalone: true,
  imports: [
    ReactiveFormsModule, RouterLink, RouterLinkActive, TranslateModule, DatePipe,
    ImpersonationBannerComponent, ButtonComponent, CardComponent, PageHeaderComponent,
    StatusChipComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-6xl space-y-6 p-6">
      <app-page-header [heading]="'admin.users.title' | translate">
        <nav actions class="flex flex-wrap items-center gap-4 text-sm">
          <a routerLink="/admin" [routerLinkActiveOptions]="{ exact: true }"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.overview' | translate }}</a>
          <a routerLink="/admin/users"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.users' | translate }}</a>
          <a routerLink="/admin/audit"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.audit' | translate }}</a>
          <a routerLink="/admin/flags"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.flags' | translate }}</a>
          <a routerLink="/admin/health"
             routerLinkActive="!text-accent-700 !border-accent" ariaCurrentWhenActive="page"
             class="border-b-2 border-transparent pb-0.5 text-ink hover:text-accent-700">{{ 'admin.nav.health' | translate }}</a>
        </nav>
      </app-page-header>

      <!-- ===== Filters ===== -->
      <form [formGroup]="filterForm" (ngSubmit)="apply()" class="flex flex-wrap items-end gap-3">
        <div>
          <label for="admin-users-q" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-700">
            {{ 'admin.users.filter.search' | translate }}
          </label>
          <input id="admin-users-q" type="text" formControlName="q"
                 [placeholder]="'admin.users.filter.search_placeholder' | translate"
                 class="rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
        </div>
        <div>
          <label for="admin-users-active" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-700">
            {{ 'admin.users.filter.active' | translate }}
          </label>
          <select id="admin-users-active" formControlName="is_active"
                  class="rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink">
            <option value="">{{ 'admin.users.filter.all' | translate }}</option>
            <option value="true">{{ 'admin.users.filter.active_yes' | translate }}</option>
            <option value="false">{{ 'admin.users.filter.active_no' | translate }}</option>
          </select>
        </div>
        <div>
          <label for="admin-users-broker" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-700">
            {{ 'admin.users.filter.broker' | translate }}
          </label>
          <select id="admin-users-broker" formControlName="has_broker"
                  class="rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink">
            <option value="">{{ 'admin.users.filter.all' | translate }}</option>
            <option value="true">{{ 'admin.users.filter.broker_yes' | translate }}</option>
            <option value="false">{{ 'admin.users.filter.broker_no' | translate }}</option>
          </select>
        </div>
        <app-button type="submit" variant="primary">
          {{ 'admin.users.filter.apply' | translate }}
        </app-button>
      </form>

      @if (admin.error(); as err) {
        <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">{{ err.message }}</div>
      }

      <!-- ===== Table ===== -->
      @if (admin.loading()) {
        <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
      } @else if (admin.users().length === 0) {
        <p class="text-sm text-neutral-700">{{ 'admin.users.empty' | translate }}</p>
      } @else {
        <app-card>
          <table class="w-full border-collapse text-[13px]">
            <thead class="text-left">
              <tr class="border-b border-divider">
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'admin.users.col.email' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'admin.users.col.name' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'admin.users.col.active' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'admin.users.col.mfa' | translate }}</th>
                <th class="px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'admin.users.col.brokers' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-700">{{ 'admin.users.col.created' | translate }}</th>
              </tr>
            </thead>
            <tbody>
              @for (u of admin.users(); track u.id) {
                <tr class="border-t border-divider hover:bg-surface">
                  <td class="px-3 py-2">
                    <a [routerLink]="['/admin/users', u.id]" class="text-accent-700 hover:underline">{{ u.email }}</a>
                    @if (u.is_staff) {
                      <span class="ml-2">
                        <app-status-chip tone="info">{{ 'admin.users.staff' | translate }}</app-status-chip>
                      </span>
                    }
                  </td>
                  <td class="px-3 py-2">{{ u.display_name }}</td>
                  <td class="px-3 py-2">
                    <app-status-chip [tone]="u.is_active ? 'up' : 'down'">
                      {{ (u.is_active ? 'admin.users.filter.active_yes' : 'admin.users.filter.active_no') | translate }}
                    </app-status-chip>
                  </td>
                  <td class="px-3 py-2">{{ (u.mfa_enabled ? 'admin.users.on' : 'admin.users.off') | translate }}</td>
                  <td class="px-3 py-2 text-right font-mono tabular-nums">{{ u.broker_count }}</td>
                  <td class="px-3 py-2 text-neutral-700">{{ u.created_at | date:'short' }}</td>
                </tr>
              }
            </tbody>
          </table>
        </app-card>

        <!-- ===== Pagination ===== -->
        <div class="flex items-center justify-between text-sm">
          <span class="text-neutral-700">
            {{ 'admin.pagination.page' | translate:{ page: admin.usersPage(), pages: admin.usersTotalPages(), total: admin.usersTotal() } }}
          </span>
          <div class="flex gap-2">
            <app-button variant="secondary" (clicked)="go(admin.usersPage() - 1)" [disabled]="admin.usersPage() <= 1">
              {{ 'admin.pagination.prev' | translate }}
            </app-button>
            <app-button variant="secondary" (clicked)="go(admin.usersPage() + 1)" [disabled]="admin.usersPage() >= admin.usersTotalPages()">
              {{ 'admin.pagination.next' | translate }}
            </app-button>
          </div>
        </div>
      }
    </div>
  `,
})
export class AdminUsersComponent implements OnInit {
  admin = inject(AdminFacade);
  private fb = inject(FormBuilder);

  filterForm = this.fb.nonNullable.group({
    q: '',
    is_active: '',
    has_broker: '',
  });

  ngOnInit(): void {
    void this.admin.loadUsers(1, {});
  }

  apply(): void {
    void this.admin.loadUsers(1, this._filters());
  }

  go(page: number): void {
    void this.admin.loadUsers(page);
  }

  private _filters(): AdminUserListParams {
    const { q, is_active, has_broker } = this.filterForm.getRawValue();
    const filters: AdminUserListParams = {};
    if (q.trim()) { filters.q = q.trim(); }
    if (is_active) { filters.is_active = is_active === 'true'; }
    if (has_broker) { filters.has_broker = has_broker === 'true'; }
    return filters;
  }
}
