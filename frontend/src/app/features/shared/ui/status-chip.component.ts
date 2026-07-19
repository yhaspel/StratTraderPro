/** Status chip ("Industry" system) — the ONE chip for every status in the app:
 * Industry `.tag` grammar, tint background + deep text (mirrors `.tag-accent`'s
 * 100/800 pattern), 11px 700, square corners. Replaces every ad-hoc
 * `bg-*-100 text-*-800` span in orders/backtest/brokers/risk/strategies.
 *
 * Semantics (angular-migration-notes.md §3 — single source of truth):
 * - up: FILLED, COMPLETED, CONNECTED, OK, release  · green is money/risk ONLY
 * - down: REJECTED, FAILED, DOWN, halt/LIVE
 * - warn: PARTIAL, CANCELLING, DEGRADED, AUTO, untested/drift
 * - bear: regime BEAR only
 * - info: SUBMITTED, RUNNING, SYSTEM (accent-100 tint / accent-800 text)
 * - neutral: PENDING_SUBMIT, CANCELLED, QUEUED, USER, PAPER
 * - outline: DEFAULT badge
 * Broker-stream chips add a square dot (`dot` input) — never color-only;
 * every status keeps its text label (projected content, i18n-translated by
 * the caller).
 */
import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';

export type ChipTone =
  | 'up'
  | 'down'
  | 'warn'
  | 'bear'
  | 'info'
  | 'neutral'
  | 'outline'
  | 'regime-bull'
  | 'regime-chop'
  | 'regime-bear'
  | 'regime-crisis'
  | 'regime-neutral';

/** Status keyword → tone (notes §3). Keys are upper-cased before lookup. */
export const STATUS_CHIP_TONE: Record<string, ChipTone> = {
  // Order lifecycle
  PENDING_SUBMIT: 'neutral',
  SUBMITTED: 'info',
  PARTIAL: 'warn',
  PARTIALLY_FILLED: 'warn',
  FILLED: 'up',
  CANCELLED: 'neutral',
  CANCELED: 'neutral',
  REJECTED: 'down',
  // Backtest lifecycle
  QUEUED: 'neutral',
  RUNNING: 'info',
  CANCELLING: 'warn',
  COMPLETED: 'up',
  FAILED: 'down',
  // Broker stream (use [dot]="true")
  CONNECTED: 'up',
  DEGRADED: 'warn',
  DOWN: 'down',
  // Regime
  BULL: 'regime-bull',
  CHOP: 'regime-chop',
  BEAR: 'regime-bear',
  CRISIS: 'regime-crisis',
  NEUTRAL: 'regime-neutral',
  // Badges
  SYSTEM: 'info',
  USER: 'neutral',
  PAPER: 'neutral',
  DEFAULT: 'outline',
  AUTO: 'warn',
  LIVE: 'down',
  UNTESTED: 'warn',
};

const TONE_CLASSES: Record<ChipTone, string> = {
  up: 'bg-up-tint text-up-deep',
  down: 'bg-down-tint text-down-deep',
  warn: 'bg-warn-tint text-warn-deep',
  bear: 'bg-bear-tint text-bear-deep',
  info: 'bg-accent-100 text-accent-800',
  neutral: 'bg-neutral-100 text-neutral-800',
  outline: 'bg-transparent border border-accent text-accent-700',
  // Regime chips reuse the tint/deep pairs of their semantic neighbours; the
  // regime hue itself drives the band/badge fills, not the chip text pair.
  'regime-bull': 'bg-up-tint text-up-deep',
  'regime-chop': 'bg-warn-tint text-warn-deep',
  'regime-bear': 'bg-bear-tint text-bear-deep',
  'regime-crisis': 'bg-down-tint text-down-deep',
  'regime-neutral': 'bg-neutral-100 text-neutral-800',
};

@Component({
  selector: 'app-status-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="inline-flex items-center gap-1.5 rounded-none px-2.5 py-[3px] text-[11px] font-bold tracking-wide {{ toneClasses() }}">
      @if (dot) {
        <span class="h-1.5 w-1.5 flex-none bg-current" aria-hidden="true"></span>
      }
      <ng-content />
    </span>
  `,
})
export class StatusChipComponent {
  /** Direct tone; wins over `status` when both are set. */
  @Input() set tone(value: ChipTone | null | undefined) {
    this._tone.set(value ?? null);
  }
  /** Raw status keyword (e.g. "FILLED"); resolved via STATUS_CHIP_TONE. */
  @Input() set status(value: string | null | undefined) {
    this._status.set(value ?? null);
  }
  /** Square dot (broker stream chips) — dot + label, never color-only. */
  @Input() dot = false;

  private readonly _tone = signal<ChipTone | null>(null);
  private readonly _status = signal<string | null>(null);

  readonly toneClasses = computed(() => {
    const tone =
      this._tone() ??
      STATUS_CHIP_TONE[(this._status() ?? '').toUpperCase().replace(/[\s-]+/g, '_')] ??
      'neutral';
    return TONE_CLASSES[tone];
  });
}
