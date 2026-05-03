/** StrategiesFacade — bridges the StrategiesApi + StrategiesStore + UI. */
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import { StrategiesApi } from '../../core/services/strategies.api';
import {
  Strategy,
  StrategyUploadPayload,
  WebhookConfig,
  WebhookRotateResponse,
} from '../../core/models/strategies.models';
import { StrategiesStore } from '../stores/strategies.store';

@Injectable({ providedIn: 'root' })
export class StrategiesFacade {
  private api = inject(StrategiesApi);
  private store = inject(StrategiesStore);

  // Re-export slices for components
  readonly strategies = this.store.strategies;
  readonly loading = this.store.loading;
  readonly error = this.store.error;

  async load(): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.list());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setStrategies(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async upload(payload: StrategyUploadPayload): Promise<{ ok: true; strategy: Strategy } | { ok: false; error: ApiError }> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.upload(payload));
      if (res.error) {
        this.store.setError(res.error);
        return { ok: false, error: res.error };
      }
      const strategy = res.data!;
      this.store.upsertStrategy(strategy);
      return { ok: true, strategy };
    } catch (err) {
      const e = this._asError(err);
      this.store.setError(e);
      return { ok: false, error: e };
    } finally {
      this.store.setLoading(false);
    }
  }

  async toggleEnabled(id: string, isEnabled: boolean): Promise<boolean> {
    const res = await firstValueFrom(this.api.patch(id, { is_enabled: isEnabled }));
    if (res.error) { this.store.setError(res.error); return false; }
    this.store.upsertStrategy(res.data!);
    return true;
  }

  async softDelete(id: string): Promise<boolean> {
    const res = await firstValueFrom(this.api.delete(id));
    if (res.error) { this.store.setError(res.error); return false; }
    // Optimistic — remove from list (it's now is_enabled=false; default list view excludes it).
    this.store.removeStrategy(id);
    return true;
  }

  // -- Webhook config -------------------------------------------------------
  async loadWebhookConfig(strategyId: string): Promise<WebhookConfig | null> {
    const res = await firstValueFrom(this.api.getWebhookConfig(strategyId));
    if (res.error) { this.store.setError(res.error); return null; }
    this.store.setWebhookConfig(strategyId, res.data!);
    return res.data!;
  }

  async updateWebhookConfig(strategyId: string, json_schema: unknown, payload_template: unknown): Promise<{ ok: boolean; error?: ApiError }> {
    const res = await firstValueFrom(this.api.putWebhookConfig(strategyId, { json_schema, payload_template }));
    if (res.error) { return { ok: false, error: res.error }; }
    // Merge — keep secret/reveal_once from cache (PUT does not return them).
    const existing = this.store.webhookConfig(strategyId)();
    this.store.setWebhookConfig(strategyId, {
      ...res.data!,
      secret: existing?.secret ?? null,
      reveal_once: existing?.reveal_once ?? false,
    });
    return { ok: true };
  }

  async rotateWebhookSecret(strategyId: string): Promise<WebhookRotateResponse | null> {
    const res = await firstValueFrom(this.api.rotateWebhookSecret(strategyId));
    if (res.error) { this.store.setError(res.error); return null; }
    const data = res.data!;
    // Refresh the cached config so `secret` + `reveal_once` show up in the modal.
    const existing = this.store.webhookConfig(strategyId)();
    this.store.setWebhookConfig(strategyId, {
      ...(existing ?? {
        version: data.version,
        json_schema: {},
        payload_template: {},
        url: data.url,
        secret: null,
        reveal_once: false,
      }),
      url: data.url,
      secret: data.secret,
      reveal_once: true,
      version: data.version,
      rotated_at: data.rotated_at,
    });
    return data;
  }

  async dryRunWebhook(strategyId: string, payload: unknown): Promise<{ ok: boolean; error?: ApiError }> {
    const res = await firstValueFrom(this.api.dryRunWebhook(strategyId, payload));
    if (res.error) { return { ok: false, error: res.error }; }
    return { ok: true };
  }

  webhookConfig(strategyId: string) {
    return this.store.webhookConfig(strategyId);
  }

  clearRevealedSecret(strategyId: string) {
    this.store.clearRevealedSecret(strategyId);
  }

  // -- helpers --------------------------------------------------------------
  private _asError(err: unknown): ApiError {
    return { code: 'UNKNOWN', message: (err as Error)?.message ?? 'Unknown error' };
  }
}
