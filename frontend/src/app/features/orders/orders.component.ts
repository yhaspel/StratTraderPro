/** /orders — order lifecycle browser (M05).
 *
 * Server-paginated table with broker/strategy/status/date filters, a row-click
 * detail drawer (order + fills lifecycle), CSV export of the filtered set, and
 * a recent reconciliation-events panel.
 */
import { Component, ElementRef, OnInit, ViewChild, inject } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { OrderListParams } from '../../core/models/orders.models';
import { OrdersFacade } from '../../abstraction/facades/orders.facade';

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
  imports: [CommonModule, ReactiveFormsModule, TranslateModule, DatePipe],
  template: `
    <div class="mx-auto max-w-6xl p-6 space-y-8">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">{{ 'orders.title' | translate }}</h1>
        <button type="button" (click)="onExport()"
                class="bg-blue-600 text-white text-sm px-4 py-2 rounded hover:bg-blue-700">
          {{ 'orders.export' | translate }}
        </button>
      </div>

      @if (facade.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded" role="alert">
          {{ err.message }}
        </div>
      }

      <!-- ========== Filters ========== -->
      <form [formGroup]="filterForm" (ngSubmit)="onApply()"
            class="flex flex-wrap items-end gap-3 border rounded-lg p-4">
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">{{ 'orders.filters.broker' | translate }}</label>
          <select formControlName="broker" class="border rounded px-3 py-2 text-sm">
            <option value="">{{ 'orders.filters.all' | translate }}</option>
            @for (b of brokers; track b) {
              <option [value]="b">{{ b }}</option>
            }
          </select>
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">{{ 'orders.filters.status' | translate }}</label>
          <select formControlName="status" class="border rounded px-3 py-2 text-sm">
            <option value="">{{ 'orders.filters.all' | translate }}</option>
            @for (s of statuses; track s) {
              <option [value]="s">{{ ('orders.status.' + s) | translate }}</option>
            }
          </select>
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">{{ 'orders.filters.strategy' | translate }}</label>
          <input type="text" formControlName="strategy" autocomplete="off"
                 class="border rounded px-3 py-2 text-sm w-48" />
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">{{ 'orders.filters.from' | translate }}</label>
          <input type="date" formControlName="from" class="border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1">{{ 'orders.filters.to' | translate }}</label>
          <input type="date" formControlName="to" class="border rounded px-3 py-2 text-sm" />
        </div>
        <button type="submit"
                class="bg-gray-800 text-white text-sm px-4 py-2 rounded hover:bg-gray-900">
          {{ 'orders.filters.apply' | translate }}
        </button>
      </form>

      <!-- ========== Orders table ========== -->
      <section>
        @if (facade.loading()) {
          <p class="text-sm text-gray-500">{{ 'common.loading' | translate }}</p>
        } @else if (facade.orders().length === 0) {
          <p class="text-sm text-gray-500">{{ 'orders.empty' | translate }}</p>
        } @else {
          <table class="w-full border border-gray-200 text-sm">
            <thead class="bg-gray-50 text-left">
              <tr>
                <th class="px-3 py-2">{{ 'orders.col.time' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.col.broker' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.col.strategy' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.col.symbol' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.col.side' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'orders.col.qty' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.col.type' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.col.status' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'orders.col.filled' | translate }}</th>
              </tr>
            </thead>
            <tbody>
              @for (o of facade.orders(); track o.id) {
                <tr class="border-t border-gray-100 cursor-pointer hover:bg-gray-50"
                    tabindex="0" role="button"
                    [attr.aria-label]="('orders.detail.title' | translate) + ': ' + o.symbol"
                    (click)="onOpen(o.id)"
                    (keydown.enter)="onOpen(o.id)"
                    (keydown.space)="$event.preventDefault(); onOpen(o.id)">
                  <td class="px-3 py-2 whitespace-nowrap">{{ o.created_at | date:'short' }}</td>
                  <td class="px-3 py-2">{{ o.broker || '—' }}</td>
                  <td class="px-3 py-2 font-mono text-xs">{{ o.strategy || '—' }}</td>
                  <td class="px-3 py-2 font-medium">{{ o.symbol }}</td>
                  <td class="px-3 py-2">{{ o.side }}</td>
                  <td class="px-3 py-2 text-right font-mono">{{ fmtQty(o.qty) }}</td>
                  <td class="px-3 py-2">{{ o.order_type }}</td>
                  <td class="px-3 py-2">
                    <span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700">
                      {{ ('orders.status.' + o.status) | translate }}
                    </span>
                  </td>
                  <td class="px-3 py-2 text-right font-mono">{{ fmtQty(o.filled_qty) }}</td>
                </tr>
              }
            </tbody>
          </table>

          <!-- Pagination -->
          <div class="mt-4 flex items-center justify-between text-sm">
            <span class="text-gray-500">
              {{ 'orders.pagination.page' | translate:{ page: facade.page(), pages: facade.numPages(), total: facade.total() } }}
            </span>
            <div class="flex gap-2">
              <button type="button" (click)="onPrev()" [disabled]="facade.page() <= 1"
                      class="px-3 py-1 border rounded hover:bg-gray-50 disabled:opacity-50">
                {{ 'orders.pagination.prev' | translate }}
              </button>
              <button type="button" (click)="onNext()" [disabled]="facade.page() >= facade.numPages()"
                      class="px-3 py-1 border rounded hover:bg-gray-50 disabled:opacity-50">
                {{ 'orders.pagination.next' | translate }}
              </button>
            </div>
          </div>
        }
      </section>

      <!-- ========== Reconciliation events ========== -->
      <section>
        <h2 class="text-lg font-semibold mb-3">{{ 'orders.recon.title' | translate }}</h2>
        @if (facade.reconEvents().length === 0) {
          <p class="text-sm text-gray-500">{{ 'orders.recon.empty' | translate }}</p>
        } @else {
          <table class="w-full border border-gray-200 text-sm">
            <thead class="bg-gray-50 text-left">
              <tr>
                <th class="px-3 py-2">{{ 'orders.recon.col.time' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.recon.col.symbol' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.recon.col.kind' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'orders.recon.col.our_qty' | translate }}</th>
                <th class="px-3 py-2 text-right">{{ 'orders.recon.col.broker_qty' | translate }}</th>
                <th class="px-3 py-2">{{ 'orders.recon.col.detail' | translate }}</th>
              </tr>
            </thead>
            <tbody>
              @for (e of facade.reconEvents(); track e.id) {
                <tr class="border-t border-gray-100">
                  <td class="px-3 py-2 whitespace-nowrap">{{ e.created_at | date:'short' }}</td>
                  <td class="px-3 py-2 font-medium">{{ e.symbol }}</td>
                  <td class="px-3 py-2">
                    <span class="text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-800">
                      {{ ('orders.recon.kind.' + e.kind) | translate }}
                    </span>
                  </td>
                  <td class="px-3 py-2 text-right font-mono">{{ fmtQty(e.our_qty) }}</td>
                  <td class="px-3 py-2 text-right font-mono">{{ fmtQty(e.broker_qty) }}</td>
                  <td class="px-3 py-2 text-xs text-gray-500">{{ e.detail || '—' }}</td>
                </tr>
              }
            </tbody>
          </table>
        }
      </section>
    </div>

    <!-- ========== Detail drawer ========== -->
    @if (facade.selected(); as o) {
      <div class="fixed inset-0 bg-black/30 z-40" (click)="onClose()"></div>
      <aside #drawer role="dialog" aria-modal="true" aria-labelledby="order-detail-title"
             tabindex="-1" (keydown.escape)="onClose()"
             class="fixed inset-y-0 right-0 w-full max-w-md bg-white shadow-xl z-50 overflow-y-auto p-6 space-y-4 focus:outline-none">
        <div class="flex items-center justify-between">
          <h2 id="order-detail-title" class="text-lg font-semibold">{{ 'orders.detail.title' | translate }}</h2>
          <button type="button" (click)="onClose()"
                  class="text-gray-400 hover:text-gray-700 text-sm">
            {{ 'orders.detail.close' | translate }}
          </button>
        </div>

        <div class="flex items-center gap-2">
          <span class="text-lg font-bold">{{ o.symbol }}</span>
          <span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700">
            {{ ('orders.status.' + o.status) | translate }}
          </span>
        </div>

        <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt class="text-gray-500">{{ 'orders.detail.field.asset_class' | translate }}</dt>
          <dd>{{ o.asset_class }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.side' | translate }}</dt>
          <dd>{{ o.side }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.type' | translate }}</dt>
          <dd>{{ o.order_type }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.tif' | translate }}</dt>
          <dd>{{ o.time_in_force }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.qty' | translate }}</dt>
          <dd class="font-mono">{{ fmtQty(o.qty) }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.filled' | translate }}</dt>
          <dd class="font-mono">{{ fmtQty(o.filled_qty) }}</dd>
          @if (o.limit_price) {
            <dt class="text-gray-500">{{ 'orders.detail.field.limit_price' | translate }}</dt>
            <dd class="font-mono">{{ fmtMoney(o.limit_price) }}</dd>
          }
          @if (o.stop_price) {
            <dt class="text-gray-500">{{ 'orders.detail.field.stop_price' | translate }}</dt>
            <dd class="font-mono">{{ fmtMoney(o.stop_price) }}</dd>
          }
          @if (o.option_expiry) {
            <dt class="text-gray-500">{{ 'orders.detail.field.option_expiry' | translate }}</dt>
            <dd>{{ o.option_expiry }}</dd>
          }
          @if (o.option_strike) {
            <dt class="text-gray-500">{{ 'orders.detail.field.option_strike' | translate }}</dt>
            <dd class="font-mono">{{ fmtMoney(o.option_strike) }}</dd>
          }
          @if (o.option_right) {
            <dt class="text-gray-500">{{ 'orders.detail.field.option_right' | translate }}</dt>
            <dd>{{ o.option_right }}</dd>
          }
          @if (o.future_root) {
            <dt class="text-gray-500">{{ 'orders.detail.field.future_root' | translate }}</dt>
            <dd>{{ o.future_root }}</dd>
          }
          @if (o.future_expiry) {
            <dt class="text-gray-500">{{ 'orders.detail.field.future_expiry' | translate }}</dt>
            <dd>{{ o.future_expiry }}</dd>
          }
          <dt class="text-gray-500">{{ 'orders.detail.field.broker' | translate }}</dt>
          <dd>{{ o.broker || '—' }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.strategy' | translate }}</dt>
          <dd class="font-mono text-xs break-all">{{ o.strategy || '—' }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.client_order_id' | translate }}</dt>
          <dd class="font-mono text-xs break-all">{{ o.client_order_id || '—' }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.broker_order_id' | translate }}</dt>
          <dd class="font-mono text-xs break-all">{{ o.broker_order_id || '—' }}</dd>
          @if (o.reason) {
            <dt class="text-gray-500">{{ 'orders.detail.field.reason' | translate }}</dt>
            <dd>{{ o.reason }}</dd>
          }
          <dt class="text-gray-500">{{ 'orders.detail.field.created' | translate }}</dt>
          <dd>{{ o.created_at | date:'medium' }}</dd>
          <dt class="text-gray-500">{{ 'orders.detail.field.updated' | translate }}</dt>
          <dd>{{ o.updated_at | date:'medium' }}</dd>
        </dl>

        <!-- Lifecycle fills -->
        <div>
          <h3 class="text-sm font-semibold mb-2">{{ 'orders.detail.fills' | translate }}</h3>
          @if (o.fills.length === 0) {
            <p class="text-sm text-gray-500">{{ 'orders.detail.no_fills' | translate }}</p>
          } @else {
            <ul class="divide-y border border-gray-200 rounded">
              @for (f of o.fills; track f.id) {
                <li class="px-3 py-2 flex items-center justify-between text-sm">
                  <span class="font-mono text-gray-600">{{ fmtQty(f.qty) }} &#64; {{ fmtMoney(f.price) }}</span>
                  <span class="text-xs text-gray-400">{{ f.ts | date:'short' }}</span>
                </li>
              }
            </ul>
          }
        </div>
      </aside>
    }
  `,
})
export class OrdersComponent implements OnInit {
  facade = inject(OrdersFacade);
  private fb = inject(FormBuilder);

  readonly statuses = ORDER_STATUSES;
  readonly brokers = BROKERS;

  /** Move focus into the detail drawer when it opens (focus management for the
   *  inline dialog — app-modal is unsuitable for a side-panel drawer layout). */
  @ViewChild('drawer') set drawer(ref: ElementRef<HTMLElement> | undefined) {
    if (ref) { queueMicrotask(() => ref.nativeElement.focus()); }
  }

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
