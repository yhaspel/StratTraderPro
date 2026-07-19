/** /admin/audit — filterable, paginated audit feed with CSV export (M10).
 *
 * Event types render via the `audit.event.*` map; unknown types fall back to the
 * raw event-type string (checked against the loaded map through TranslateService
 * so a missing key doesn't print the key path).
 *
 * Industry styling: sub-nav with accent underline, dense blueprint table with
 * mono actor/IP/hash columns; hash-chain values wrap with break-all.
 */
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { AuditFilters } from '../../core/models/admin.models';
import { ImpersonationBannerComponent } from './impersonation-banner.component';
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';

@Component({
  selector: 'app-admin-audit',
  standalone: true,
  imports: [
    ReactiveFormsModule, RouterLink, RouterLinkActive, TranslateModule, DatePipe,
    ImpersonationBannerComponent, ButtonComponent, CardComponent, PageHeaderComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-impersonation-banner />

    <div class="mx-auto max-w-6xl space-y-6 p-6">
      <app-page-header [heading]="'admin.audit.title' | translate">
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
      <form [formGroup]="filterForm" (ngSubmit)="apply()" class="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div>
          <label for="audit-user" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.filter.user' | translate }}</label>
          <input id="audit-user" type="text" formControlName="user" class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
        </div>
        <div>
          <label for="audit-actor" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.filter.actor' | translate }}</label>
          <input id="audit-actor" type="text" formControlName="actor" class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
        </div>
        <div>
          <label for="audit-event" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.filter.event_type' | translate }}</label>
          <input id="audit-event" type="text" formControlName="event_type" class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
        </div>
        <div>
          <label for="audit-entity-type" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.filter.entity_type' | translate }}</label>
          <input id="audit-entity-type" type="text" formControlName="entity_type" class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
        </div>
        <div>
          <label for="audit-entity-id" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.filter.entity_id' | translate }}</label>
          <input id="audit-entity-id" type="text" formControlName="entity_id" class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink" />
        </div>
        <div>
          <label for="audit-after" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.filter.after' | translate }}</label>
          <input id="audit-after" type="date" formControlName="occurred_after" class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
        </div>
        <div>
          <label for="audit-before" class="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.filter.before' | translate }}</label>
          <input id="audit-before" type="date" formControlName="occurred_before" class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink" />
        </div>
        <div class="flex items-end gap-2">
          <app-button type="submit" variant="primary">
            {{ 'admin.audit.filter.apply' | translate }}
          </app-button>
          <app-button variant="secondary" (clicked)="exportCsv()">
            {{ 'admin.audit.export' | translate }}
          </app-button>
        </div>
      </form>

      @if (admin.error(); as err) {
        <div class="rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">{{ err.message }}</div>
      }

      <!-- ===== Table ===== -->
      @if (admin.loading()) {
        <p class="text-sm text-neutral-600">{{ 'common.loading' | translate }}</p>
      } @else if (admin.audit().length === 0) {
        <p class="text-sm text-neutral-600">{{ 'admin.audit.empty' | translate }}</p>
      } @else {
        <app-card>
          <table class="w-full border-collapse text-[13px]">
            <thead class="text-left">
              <tr class="border-b border-divider">
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.col.time' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.col.event' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.col.actor' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.col.entity' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.col.ip' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-600">{{ 'admin.audit.col.hash' | translate }}</th>
              </tr>
            </thead>
            <tbody>
              @for (a of admin.audit(); track a.id) {
                <tr class="border-t border-divider">
                  <td class="whitespace-nowrap px-3 py-2 text-neutral-600">{{ a.occurred_at | date:'short' }}</td>
                  <td class="px-3 py-2 font-medium">{{ eventLabel(a.event_type) }}</td>
                  <td class="px-3 py-2 font-mono text-xs">{{ a.actor || '—' }}</td>
                  <td class="px-3 py-2 text-xs">{{ a.entity_type || '—' }}@if (a.entity_id) {<span class="font-mono"> · {{ a.entity_id }}</span>}</td>
                  <td class="px-3 py-2 font-mono text-xs tabular-nums">{{ a.ip || '—' }}</td>
                  <td class="max-w-[180px] break-all px-3 py-2 font-mono text-xs text-neutral-600">{{ a.self_hash }}</td>
                </tr>
              }
            </tbody>
          </table>
        </app-card>

        <!-- ===== Pagination ===== -->
        <div class="flex items-center justify-between text-sm">
          <span class="text-neutral-600">
            {{ 'admin.pagination.page' | translate:{ page: admin.auditPage(), pages: admin.auditTotalPages(), total: admin.auditTotal() } }}
          </span>
          <div class="flex gap-2">
            <app-button variant="secondary" (clicked)="go(admin.auditPage() - 1)" [disabled]="admin.auditPage() <= 1">
              {{ 'admin.pagination.prev' | translate }}
            </app-button>
            <app-button variant="secondary" (clicked)="go(admin.auditPage() + 1)" [disabled]="admin.auditPage() >= admin.auditTotalPages()">
              {{ 'admin.pagination.next' | translate }}
            </app-button>
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
