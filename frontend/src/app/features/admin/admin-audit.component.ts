/** /admin/audit — filterable, paginated audit feed with CSV export (M10).
 *
 * Event types render via the `audit.event.*` map; unknown types fall back to the
 * raw event-type string (checked against the loaded map through TranslateService
 * so a missing key doesn't print the key path).
 */
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { AuditFilters } from '../../core/models/admin.models';
import { ImpersonationBannerComponent } from './impersonation-banner.component';

@Component({
  selector: 'app-admin-audit',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, TranslateModule, DatePipe, ImpersonationBannerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-6xl p-6 space-y-6">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">{{ 'admin.audit.title' | translate }}</h1>
        <a routerLink="/admin" class="text-sm text-blue-600 hover:underline">{{ 'admin.nav.back' | translate }}</a>
      </div>

      <!-- ===== Filters ===== -->
      <form [formGroup]="filterForm" (ngSubmit)="apply()" class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div>
          <label for="audit-user" class="block text-xs font-semibold text-gray-700 uppercase mb-1">{{ 'admin.audit.filter.user' | translate }}</label>
          <input id="audit-user" type="text" formControlName="user" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label for="audit-actor" class="block text-xs font-semibold text-gray-700 uppercase mb-1">{{ 'admin.audit.filter.actor' | translate }}</label>
          <input id="audit-actor" type="text" formControlName="actor" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label for="audit-event" class="block text-xs font-semibold text-gray-700 uppercase mb-1">{{ 'admin.audit.filter.event_type' | translate }}</label>
          <input id="audit-event" type="text" formControlName="event_type" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label for="audit-entity-type" class="block text-xs font-semibold text-gray-700 uppercase mb-1">{{ 'admin.audit.filter.entity_type' | translate }}</label>
          <input id="audit-entity-type" type="text" formControlName="entity_type" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label for="audit-entity-id" class="block text-xs font-semibold text-gray-700 uppercase mb-1">{{ 'admin.audit.filter.entity_id' | translate }}</label>
          <input id="audit-entity-id" type="text" formControlName="entity_id" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label for="audit-after" class="block text-xs font-semibold text-gray-700 uppercase mb-1">{{ 'admin.audit.filter.after' | translate }}</label>
          <input id="audit-after" type="date" formControlName="occurred_after" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label for="audit-before" class="block text-xs font-semibold text-gray-700 uppercase mb-1">{{ 'admin.audit.filter.before' | translate }}</label>
          <input id="audit-before" type="date" formControlName="occurred_before" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div class="flex items-end gap-2">
          <button type="submit" class="bg-blue-600 text-white text-sm px-4 py-2 rounded hover:bg-blue-700">
            {{ 'admin.audit.filter.apply' | translate }}
          </button>
          <button type="button" (click)="exportCsv()" class="border text-sm px-4 py-2 rounded hover:bg-gray-50">
            {{ 'admin.audit.export' | translate }}
          </button>
        </div>
      </form>

      @if (admin.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">{{ err.message }}</div>
      }

      <!-- ===== Table ===== -->
      @if (admin.loading()) {
        <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
      } @else if (admin.audit().length === 0) {
        <p class="text-sm text-gray-500">{{ 'admin.audit.empty' | translate }}</p>
      } @else {
        <table class="w-full border border-gray-200 text-sm">
          <thead class="bg-gray-50 text-left">
            <tr>
              <th class="px-3 py-2">{{ 'admin.audit.col.time' | translate }}</th>
              <th class="px-3 py-2">{{ 'admin.audit.col.event' | translate }}</th>
              <th class="px-3 py-2">{{ 'admin.audit.col.actor' | translate }}</th>
              <th class="px-3 py-2">{{ 'admin.audit.col.entity' | translate }}</th>
              <th class="px-3 py-2">{{ 'admin.audit.col.ip' | translate }}</th>
            </tr>
          </thead>
          <tbody>
            @for (a of admin.audit(); track a.id) {
              <tr class="border-t border-gray-100">
                <td class="px-3 py-2 text-gray-500 whitespace-nowrap">{{ a.occurred_at | date:'short' }}</td>
                <td class="px-3 py-2 font-medium">{{ eventLabel(a.event_type) }}</td>
                <td class="px-3 py-2 font-mono text-xs">{{ a.actor || '—' }}</td>
                <td class="px-3 py-2 text-xs">{{ a.entity_type || '—' }}{{ a.entity_id ? (' · ' + a.entity_id) : '' }}</td>
                <td class="px-3 py-2 font-mono text-xs">{{ a.ip || '—' }}</td>
              </tr>
            }
          </tbody>
        </table>

        <!-- ===== Pagination ===== -->
        <div class="flex items-center justify-between text-sm">
          <span class="text-gray-600">
            {{ 'admin.pagination.page' | translate:{ page: admin.auditPage(), pages: admin.auditTotalPages(), total: admin.auditTotal() } }}
          </span>
          <div class="flex gap-2">
            <button type="button" (click)="go(admin.auditPage() - 1)" [disabled]="admin.auditPage() <= 1"
                    class="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50">
              {{ 'admin.pagination.prev' | translate }}
            </button>
            <button type="button" (click)="go(admin.auditPage() + 1)" [disabled]="admin.auditPage() >= admin.auditTotalPages()"
                    class="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50">
              {{ 'admin.pagination.next' | translate }}
            </button>
          </div>
        </div>
      }
    </div>
  `,
})
export class AdminAuditComponent implements OnInit {
  admin = inject(AdminFacade);
  private fb = inject(FormBuilder);
  private translate = inject(TranslateService);

  filterForm = this.fb.nonNullable.group({
    user: '',
    actor: '',
    event_type: '',
    entity_type: '',
    entity_id: '',
    occurred_after: '',
    occurred_before: '',
  });

  ngOnInit(): void {
    void this.admin.loadAudit(1, {});
  }

  /** Translate the event type; fall back to the raw string when unmapped. */
  eventLabel(type: string): string {
    const key = `audit.event.${type}`;
    const label = this.translate.instant(key);
    return label === key ? type : label;
  }

  apply(): void {
    void this.admin.loadAudit(1, this._filters());
  }

  go(page: number): void {
    void this.admin.loadAudit(page);
  }

  exportCsv(): void {
    this.admin.setAuditFiltersAndExport(this._filters());
  }

  private _filters(): AuditFilters {
    const v = this.filterForm.getRawValue();
    const f: AuditFilters = {};
    if (v.user.trim()) { f.user = v.user.trim(); }
    if (v.actor.trim()) { f.actor = v.actor.trim(); }
    if (v.event_type.trim()) { f.event_type = v.event_type.trim(); }
    if (v.entity_type.trim()) { f.entity_type = v.entity_type.trim(); }
    if (v.entity_id.trim()) { f.entity_id = v.entity_id.trim(); }
    if (v.occurred_after) { f.occurred_after = v.occurred_after; }
    if (v.occurred_before) { f.occurred_before = v.occurred_before; }
    return f;
  }
}
