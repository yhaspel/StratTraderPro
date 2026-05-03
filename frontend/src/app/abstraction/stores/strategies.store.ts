/** Signal-based store for the strategies feature. */
import { Injectable, computed, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import { Strategy, WebhookConfig } from '../../core/models/strategies.models';

@Injectable({ providedIn: 'root' })
export class StrategiesStore {
  private readonly _strategies = signal<Strategy[]>([]);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  /** Per-strategy webhook config cache. Reveal-once secrets are stored
   *  here transiently and cleared by `clearRevealedSecret` after they
   *  hit the UI once. */
  private readonly _webhookConfigs = signal<Record<string, WebhookConfig>>({});

  readonly strategies = this._strategies.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  readonly count = computed(() => this._strategies().length);
  readonly systemCount = computed(() => this._strategies().filter(s => s.is_system).length);
  readonly userCount = computed(() => this._strategies().filter(s => !s.is_system).length);

  setLoading(loading: boolean) { this._loading.set(loading); }
  setError(err: ApiError | null) { this._error.set(err); }
  setStrategies(strategies: Strategy[]) {
    this._strategies.set(strategies);
    this._error.set(null);
  }

  upsertStrategy(s: Strategy) {
    const next = this._strategies().filter(x => x.id !== s.id);
    next.push(s);
    next.sort((a, b) => Number(b.is_system) - Number(a.is_system) || a.name.localeCompare(b.name));
    this._strategies.set(next);
  }

  removeStrategy(id: string) {
    this._strategies.set(this._strategies().filter(s => s.id !== id));
  }

  // -- Webhook config cache -------------------------------------------------
  webhookConfig(strategyId: string) {
    return computed(() => this._webhookConfigs()[strategyId] ?? null);
  }

  setWebhookConfig(strategyId: string, cfg: WebhookConfig) {
    this._webhookConfigs.set({ ...this._webhookConfigs(), [strategyId]: cfg });
  }

  /** Wipe the plaintext secret after the UI has rendered it once. */
  clearRevealedSecret(strategyId: string) {
    const cur = this._webhookConfigs()[strategyId];
    if (!cur) { return; }
    const cleaned: WebhookConfig = { ...cur, secret: null, reveal_once: false };
    this._webhookConfigs.set({ ...this._webhookConfigs(), [strategyId]: cleaned });
  }
}
