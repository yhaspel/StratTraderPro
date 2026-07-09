/** /admin/users — searchable, filterable, paginated user table (M10). */
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { AdminUserListParams } from '../../core/models/admin.models';
import { ImpersonationBannerComponent } from './impersonation-banner.component';

@Component({
  selector: 'app-admin-users',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, TranslateModule, DatePipe, ImpersonationBannerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-6xl p-6 space-y-6">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">{{ 'admin.users.title' | translate }}</h1>
        <a routerLink="/admin" class="text-sm text-blue-600 hover:underline">{{ 'admin.nav.back' | translate }}</a>
      </div>

      <!-- ===== Filters ===== -->
      <form [formGroup]="filterForm" (ngSubmit)="apply()" class="flex flex-wrap items-end gap-3">
        <div>
          <label for="admin-users-q" class="block text-xs font-semibold text-gray-700 uppercase mb-1">
            {{ 'admin.users.filter.search' | translate }}
          </label>
          <input id="admin-users-q" type="text" formControlName="q"
                 [placeholder]="'admin.users.filter.search_placeholder' | translate"
                 class="border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label for="admin-users-active" class="block text-xs font-semibold text-gray-700 uppercase mb-1">
            {{ 'admin.users.filter.active' | translate }}
          </label>
          <select id="admin-users-active" formControlName="is_active" class="border rounded px-3 py-2 text-sm">
            <option value="">{{ 'admin.users.filter.all' | translate }}</option>
            <option value="true">{{ 'admin.users.filter.active_yes' | translate }}</option>
            <option value="false">{{ 'admin.users.filter.active_no' | translate }}</option>
          </select>
        </div>
        <div>
          <label for="admin-users-broker" class="block text-xs font-semibold text-gray-700 uppercase mb-1">
            {{ 'admin.users.filter.broker' | translate }}
          </label>
          <select id="admin-users-broker" formControlName="has_broker" class="border rounded px-3 py-2 text-sm">
            <option value="">{{ 'admin.users.filter.all' | translate }}</option>
            <option value="true">{{ 'admin.users.filter.broker_yes' | translate }}</option>
            <option value="false">{{ 'admin.users.filter.broker_no' | translate }}</option>
          </select>
        </div>
        <button type="submit" class="bg-blue-600 text-white text-sm px-4 py-2 rounded hover:bg-blue-700">
          {{ 'admin.users.filter.apply' | translate }}
        </button>
      </form>

      @if (admin.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">{{ err.message }}</div>
      }

      <!-- ===== Table ===== -->
      @if (admin.loading()) {
        <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
      } @else if (admin.users().length === 0) {
        <p class="text-sm text-gray-500">{{ 'admin.users.empty' | translate }}</p>
      } @else {
        <table class="w-full border border-gray-200 text-sm">
          <thead class="bg-gray-50 text-left">
            <tr>
              <th class="px-3 py-2">{{ 'admin.users.col.email' | translate }}</th>
              <th class="px-3 py-2">{{ 'admin.users.col.name' | translate }}</th>
              <th class="px-3 py-2">{{ 'admin.users.col.active' | translate }}</th>
              <th class="px-3 py-2">{{ 'admin.users.col.mfa' | translate }}</th>
              <th class="px-3 py-2 text-right">{{ 'admin.users.col.brokers' | translate }}</th>
              <th class="px-3 py-2">{{ 'admin.users.col.created' | translate }}</th>
            </tr>
          </thead>
          <tbody>
            @for (u of admin.users(); track u.id) {
              <tr class="border-t border-gray-100 hover:bg-gray-50">
                <td class="px-3 py-2">
                  <a [routerLink]="['/admin/users', u.id]" class="text-blue-600 hover:underline">{{ u.email }}</a>
                  @if (u.is_staff) {
                    <span class="ml-2 text-xs bg-purple-100 text-purple-700 rounded px-1.5 py-0.5">
                      {{ 'admin.users.staff' | translate }}
                    </span>
                  }
                </td>
                <td class="px-3 py-2">{{ u.display_name }}</td>
                <td class="px-3 py-2">
                  <span [class.text-green-700]="u.is_active" [class.text-red-700]="!u.is_active">
                    {{ (u.is_active ? 'admin.users.filter.active_yes' : 'admin.users.filter.active_no') | translate }}
                  </span>
                </td>
                <td class="px-3 py-2">{{ (u.mfa_enabled ? 'admin.users.on' : 'admin.users.off') | translate }}</td>
                <td class="px-3 py-2 text-right font-mono">{{ u.broker_count }}</td>
                <td class="px-3 py-2 text-gray-500">{{ u.created_at | date:'short' }}</td>
              </tr>
            }
          </tbody>
        </table>

        <!-- ===== Pagination ===== -->
        <div class="flex items-center justify-between text-sm">
          <span class="text-gray-600">
            {{ 'admin.pagination.page' | translate:{ page: admin.usersPage(), pages: admin.usersTotalPages(), total: admin.usersTotal() } }}
          </span>
          <div class="flex gap-2">
            <button type="button" (click)="go(admin.usersPage() - 1)" [disabled]="admin.usersPage() <= 1"
                    class="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50">
              {{ 'admin.pagination.prev' | translate }}
            </button>
            <button type="button" (click)="go(admin.usersPage() + 1)" [disabled]="admin.usersPage() >= admin.usersTotalPages()"
                    class="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50">
              {{ 'admin.pagination.next' | translate }}
            </button>
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
