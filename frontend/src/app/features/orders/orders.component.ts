/** /orders — order lifecycle browser (M05).
 *
 * Server-paginated table with broker/strategy/status/date filters, a row-click
 * detail drawer (order + fills lifecycle), CSV export of the filtered set, and
 * a recent reconciliation-events panel.
 *
 * Visual layer: "Industry" design system — blueprint-framed panels, dense
 * mono-numeric table, shared status chips and the shared app-drawer.
 */
import { Component, OnInit, inject } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { OrderListParams } from '../../core/models/orders.models';
import { OrdersFacade } from '../../abstraction/facades/orders.facade';
import { BlueprintDirective } from '../shared/ui/blueprint.directive';
import { ButtonComponent } from '../shared/ui/button.component';
import { CardComponent } from '../shared/ui/card.component';
import { DrawerComponent } from '../shared/ui/drawer.component';
import { PageHeaderComponent } from '../shared/ui/page-header.component';
import { StatusChipComponent } from '../shared/ui/status-chip.component';

/** Order statuses (matches backend Order.Status). */
const ORDER_STATUSES = [
  'PENDING_SUBMIT',
  'SUBMITTED',
  'PARTIAL',
  'FILLED',
  'CANCELLED',
  'REJECTED',
] as const;

const BROKERS = ['ALPACA', 'TRADESTATION'] as const;

@Component({
  selector: 'app-orders',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, TranslateModule, DatePipe,
    BlueprintDirective, ButtonComponent, CardComponent, DrawerComponent,
    PageHeaderComponent, StatusChipComponent,
  ],
  template: `
    <div class="mx-auto max-w-6xl p-6 space-y-s6">
      <app-page-header [heading]="'orders.title' | translate">
        <app-button actions variant="secondary" (clicked)="onExport()">
          {{ 'orders.export' | translate }}
        </app-button>
      </app-page-header>

      @if (facade.error(); as err) {
        <div class="rounded-none border border-down bg-down-tint px-s4 py-s3 text-sm text-down-deep" role="alert">
          {{ err.message }}
        </div>
      }

      <!-- ========== Filters (one toolbar row) ========== -->
      <app-card>
        <form [formGroup]="filterForm" (ngSubmit)="onApply()"
              class="flex flex-wrap items-end gap-3">
          <div>
            <label class="mb-1 block text-xs text-neutral-700">{{ 'orders.filters.broker' | translate }}</label>
            <select formControlName="broker"
                    class="min-h-[36px] rounded-none border border-divider bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none">
              <option value="">{{ 'orders.filters.all' | translate }}</option>
              @for (b of brokers; track b) {
                <option [value]="b">{{ b }}</option>
              }
            </select>
          </div>
          <div>
            <label class="mb-1 block text-xs text-neutral-700">{{ 'orders.filters.status' | translate }}</label>
            <select formControlName="status"
                    class="min-h-[36px] rounded-none border border-divider bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-accent focus:outline-none">
              <option value="">{{ 'orders.filters.all' | translate }}</option>
              @for (s of statuses; track s) {
                <option [value]="s">{{ ('orders.status.' + s) | translate }}</option>
              }
            </select>
          </div>
          <div>
            <label class="mb-1 block text-xs text-neutral-700">{{ 'orders.filters.strategy' | translate }}</label>
            <input type="text" formControlName="strategy" autocomplete="off"
                   class="min-h-[36px] w-48 rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-xs text-ink focus:border-accent focus:outline-none" />
          </div>
          <div>
            <label class="mb-1 block text-xs text-neutral-700">{{ 'orders.filters.from' | translate }}</label>
            <input type="date" formControlName="from"
                   class="min-h-[36px] rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-xs text-ink focus:border-accent focus:outline-none" />
          </div>
          <div>
            <label class="mb-1 block text-xs text-neutral-700">{{ 'orders.filters.to' | translate }}</label>
            <input type="date" formControlName="to"
                   class="min-h-[36px] rounded-none border border-divider bg-surface px-2.5 py-1.5 font-mono text-xs text-ink focus:border-accent focus:outline-none" />
          </div>
          <app-button type="submit" variant="primary">
            {{ 'orders.filters.apply' | translate }}
          </app-button>
        </form>
      </app-card>

      <!-- ========== Orders table ========== -->
      <section>
        @if (facade.loading()) {
          <p class="text-sm text-neutral-700">{{ 'common.loading' | translate }}</p>
        } @else if (facade.orders().length === 0) {
          <p class="text-sm text-neutral-700">{{ 'orders.empty' | translate }}</p>
        } @else {
          <div stpBlueprint class="bg-transparent">
            <table class="w-full text-[13px]">
              <thead class="text-left">
                <tr class="border-b border-divider">
                  <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.time' | translate }}</th>
                  <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.broker' | translate }}</th>
                  <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.strategy' | translate }}</th>
                  <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.symbol' | translate }}</th>
                  <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.side' | translate }}</th>
                  <th class="px-3 py-2 text-right text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.qty' | translate }}</th>
                  <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.type' | translate }}</th>
                  <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.status' | translate }}</th>
                  <th class="px-3 py-2 text-right text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.col.filled' | translate }}</th>
                </tr>
              </thead>
              <tbody>
                @for (o of facade.orders(); track o.id) {
                  <tr class="h-9 cursor-pointer border-t border-neutral-200 hover:bg-neutral-100"
                      tabindex="0" role="button"
                      [attr.aria-label]="('orders.detail.title' | translate) + ': ' + o.symbol"
                      (click)="onOpen(o.id)"
                      (keydown.enter)="onOpen(o.id)"
                      (keydown.space)="$event.preventDefault(); onOpen(o.id)">
                    <td class="whitespace-nowrap px-3 py-1.5 font-mono text-xs text-neutral-700">{{ o.created_at | date:'short' }}</td>
                    <td class="px-3 py-1.5 text-neutral-700">{{ o.broker || '—' }}</td>
                    <td class="px-3 py-1.5 font-mono text-xs text-neutral-700">{{ o.strategy || '—' }}</td>
                    <td class="px-3 py-1.5 font-bold">{{ o.symbol }}</td>
                    <td class="px-3 py-1.5 font-mono text-xs"
                        [ngClass]="{ 'text-up': o.side === 'BUY', 'text-down': o.side === 'SELL' }">{{ o.side }}</td>
                    <td class="px-3 py-1.5 text-right font-mono tabular-nums">{{ fmtQty(o.qty) }}</td>
                    <td class="px-3 py-1.5 text-neutral-700">{{ o.order_type }}</td>
                    <td class="px-3 py-1.5">
                      <app-status-chip [status]="o.status">
                        {{ ('orders.status.' + o.status) | translate }}
                      </app-status-chip>
                    </td>
                    <td class="px-3 py-1.5 text-right font-mono tabular-nums">{{ fmtQty(o.filled_qty) }}</td>
                  </tr>
                }
              </tbody>
            </table>

            <!-- Pagination -->
            <div class="flex items-center justify-between border-t border-divider px-4 py-2.5">
              <span class="font-mono text-xs text-neutral-700">
                {{ 'orders.pagination.page' | translate:{ page: facade.page(), pages: facade.numPages(), total: facade.total() } }}
              </span>
              <div class="flex gap-2">
                <app-button variant="secondary" [disabled]="facade.page() <= 1" (clicked)="onPrev()">
                  {{ 'orders.pagination.prev' | translate }}
                </app-button>
                <app-button variant="secondary" [disabled]="facade.page() >= facade.numPages()" (clicked)="onNext()">
                  {{ 'orders.pagination.next' | translate }}
                </app-button>
              </div>
            </div>
          </div>
        }
      </section>

      <!-- ========== Reconciliation events ========== -->
      <section stpBlueprint class="block bg-transparent px-4 py-3.5">
        <h2 class="mb-1.5 font-heading text-[13px] font-semibold uppercase tracking-[0.08em] text-neutral-700">
          {{ 'orders.recon.title' | translate }}
        </h2>
        @if (facade.reconEvents().length === 0) {
          <p class="text-sm text-neutral-700">{{ 'orders.recon.empty' | translate }}</p>
        } @else {
          <table class="w-full text-[13px]">
            <thead class="text-left">
              <tr class="border-b border-divider">
                <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.recon.col.time' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.recon.col.symbol' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.recon.col.kind' | translate }}</th>
                <th class="px-3 py-2 text-right text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.recon.col.our_qty' | translate }}</th>
                <th class="px-3 py-2 text-right text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.recon.col.broker_qty' | translate }}</th>
                <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-neutral-700">{{ 'orders.recon.col.detail' | translate }}</th>
              </tr>
            </thead>
            <tbody>
              @for (e of facade.reconEvents(); track e.id) {
                <tr class="h-9 border-t border-neutral-200">
                  <td class="whitespace-nowrap px-3 py-1.5 font-mono text-xs text-neutral-700">{{ e.created_at | date:'short' }}</td>
                  <td class="px-3 py-1.5 font-bold">{{ e.symbol }}</td>
                  <td class="px-3 py-1.5">
                    <app-status-chip tone="warn">
                      {{ ('orders.recon.kind.' + e.kind) | translate }}
                    </app-status-chip>
                  </td>
                  <td class="px-3 py-1.5 text-right font-mono tabular-nums">{{ fmtQty(e.our_qty) }}</td>
                  <td class="px-3 py-1.5 text-right font-mono tabular-nums">{{ fmtQty(e.broker_qty) }}</td>
                  <td class="px-3 py-1.5 text-xs text-neutral-700">{{ e.detail || '—' }}</td>
                </tr>
              }
            </tbody>
          </table>
        }
      </section>
    </div>

    <!-- ========== Detail drawer ========== -->
    <app-drawer [open]="!!facade.selected()"
                [heading]="'orders.detail.title' | translate"
                [closeLabel]="'orders.detail.close' | translate"
                (closed)="onClose()">
      @if (facade.selected(); as o) {
        <div class="flex items-center gap-2.5">
          <span class="font-heading text-2xl font-semibold">{{ o.symbol }}</span>
          <app-status-chip [status]="o.status">
            {{ ('orders.status.' + o.status) | translate }}
          </app-status-chip>
        </div>

        <dl class="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[13px]">
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.asset_class' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ o.asset_class }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.side' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ o.side }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.type' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ o.order_type }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.tif' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ o.time_in_force }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.qty' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs tabular-nums">{{ fmtQty(o.qty) }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.filled' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs tabular-nums">{{ fmtQty(o.filled_qty) }}</dd>
          </div>
          @if (o.limit_price) {
            <div>
              <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.limit_price' | translate }}</dt>
              <dd class="mt-0.5 font-mono text-xs tabular-nums">{{ fmtMoney(o.limit_price) }}</dd>
            </div>
          }
          @if (o.stop_price) {
            <div>
              <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.stop_price' | translate }}</dt>
              <dd class="mt-0.5 font-mono text-xs tabular-nums">{{ fmtMoney(o.stop_price) }}</dd>
            </div>
          }
          @if (o.option_expiry) {
            <div>
              <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.option_expiry' | translate }}</dt>
              <dd class="mt-0.5 font-mono text-xs">{{ o.option_expiry }}</dd>
            </div>
          }
          @if (o.option_strike) {
            <div>
              <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.option_strike' | translate }}</dt>
              <dd class="mt-0.5 font-mono text-xs tabular-nums">{{ fmtMoney(o.option_strike) }}</dd>
            </div>
          }
          @if (o.option_right) {
            <div>
              <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.option_right' | translate }}</dt>
              <dd class="mt-0.5 font-mono text-xs">{{ o.option_right }}</dd>
            </div>
          }
          @if (o.future_root) {
            <div>
              <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.future_root' | translate }}</dt>
              <dd class="mt-0.5 font-mono text-xs">{{ o.future_root }}</dd>
            </div>
          }
          @if (o.future_expiry) {
            <div>
              <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.future_expiry' | translate }}</dt>
              <dd class="mt-0.5 font-mono text-xs">{{ o.future_expiry }}</dd>
            </div>
          }
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.broker' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ o.broker || '—' }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.strategy' | translate }}</dt>
            <dd class="mt-0.5 break-all font-mono text-xs">{{ o.strategy || '—' }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.client_order_id' | translate }}</dt>
            <dd class="mt-0.5 break-all font-mono text-xs">{{ o.client_order_id || '—' }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.broker_order_id' | translate }}</dt>
            <dd class="mt-0.5 break-all font-mono text-xs">{{ o.broker_order_id || '—' }}</dd>
          </div>
          @if (o.reason) {
            <div>
              <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.reason' | translate }}</dt>
              <dd class="mt-0.5 font-mono text-xs">{{ o.reason }}</dd>
            </div>
          }
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.created' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ o.created_at | date:'medium' }}</dd>
          </div>
          <div>
            <dt class="text-[11px] text-neutral-700">{{ 'orders.detail.field.updated' | translate }}</dt>
            <dd class="mt-0.5 font-mono text-xs">{{ o.updated_at | date:'medium' }}</dd>
          </div>
        </dl>

        <!-- Lifecycle fills -->
        <div class="flex flex-col gap-2">
          <h3 class="text-[10px] font-medium uppercase tracking-[0.1em] text-accent-700">
            {{ 'orders.detail.fills' | translate }}
          </h3>
          @if (o.fills.length === 0) {
            <p class="text-sm text-neutral-700">{{ 'orders.detail.no_fills' | translate }}</p>
          } @else {
            <ul class="divide-y divide-neutral-200 border border-divider">
              @for (f of o.fills; track f.id) {
                <li class="flex items-center justify-between px-3 py-2 font-mono text-xs">
                  <span class="tabular-nums">{{ fmtQty(f.qty) }} &#64; {{ fmtMoney(f.price) }}</span>
                  <span class="text-neutral-700">{{ f.ts | date:'short' }}</span>
                </li>
              }
            </ul>
          }
        </div>
      }
    </app-drawer>
  `,
})
export class OrdersComponent implements OnInit {
  facade = inject(OrdersFacade);
  private fb = inject(FormBuilder);

  readonly statuses = ORDER_STATUSES;
  readonly brokers = BROKERS;

  filterForm = this.fb.nonNullable.group({
    broker: [''],
    status: [''],
    strategy: [''],
    from: [this.daysAgo(30)],
    to: [this.today()],
  });

  ngOnInit(): void {
    void this.facade.load(1, this.buildParams());
    void this.facade.loadReconEvents();
  }

  onApply(): void {
    void this.facade.load(1, this.buildParams());
  }

  onPrev(): void {
    if (this.facade.page() > 1) {
      void this.facade.load(this.facade.page() - 1);
    }
  }

  onNext(): void {
    if (this.facade.page() < this.facade.numPages()) {
      void this.facade.load(this.facade.page() + 1);
    }
  }

  onOpen(id: string): void {
    void this.facade.openDetail(id);
  }

  onClose(): void {
    this.facade.closeDetail();
  }

  onExport(): void {
    void this.facade.exportCsv();
  }

  fmtMoney(value: string | null): string {
    if (value == null) { return '—'; }
    const n = Number(value);
    if (!isFinite(n)) { return value; }
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
  }

  fmtQty(value: string): string {
    const n = Number(value);
    if (!isFinite(n)) { return value; }
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(n);
  }

  /** Build API filter params from the form; blanks are dropped and dates are
   *  widened to a full-day datetime window (the backend parses ISO datetimes). */
  private buildParams(): OrderListParams {
    const v = this.filterForm.getRawValue();
    const params: OrderListParams = {};
    if (v.broker) { params.broker = v.broker; }
    if (v.status) { params.status = v.status; }
    if (v.strategy.trim()) { params.strategy = v.strategy.trim(); }
    if (v.from) { params.from = `${v.from}T00:00:00`; }
    if (v.to) { params.to = `${v.to}T23:59:59`; }
    return params;
  }

  private today(): string {
    return new Date().toISOString().slice(0, 10);
  }

  private daysAgo(days: number): string {
    const d = new Date();
    d.setDate(d.getDate() - days);
    return d.toISOString().slice(0, 10);
  }
}
