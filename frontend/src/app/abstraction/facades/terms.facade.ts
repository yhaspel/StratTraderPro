/** Terms re-acceptance facade (M11 §7.8) — signal-backed blocking-gate state.
 *
 * Loaded once on authenticated app load (ShellComponent). When the backend
 * reports `needs_acceptance`, the shell renders a blocking modal keyed off
 * `needsAcceptance()`; a successful accept clears the gate. A stale-version
 * 409 (TERMS_VERSION_MISMATCH) re-fetches the current versions so the user
 * re-accepts against the new ones rather than getting stuck.
 */
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { TermsApi } from '../../core/services/terms.api';
import { TermsCurrent } from '../../core/models/terms.models';
import { ApiError } from '../../core/models/auth.models';

@Injectable({ providedIn: 'root' })
export class TermsFacade {
  private api = inject(TermsApi);

  private readonly _terms = signal<TermsCurrent | null>(null);
  private readonly _accepting = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly terms = this._terms.asReadonly();
  readonly accepting = this._accepting.asReadonly();
  readonly error = this._error.asReadonly();

  /** Drives the blocking modal — true only once loaded AND acceptance is due. */
  readonly needsAcceptance = computed(() => this._terms()?.needs_acceptance === true);

  async load(): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.current());
      if (res.data) { this._terms.set(res.data); }
    } catch {
      // Best-effort: if the versions can't be fetched, don't block the app.
    }
  }

  async accept(): Promise<boolean> {
    const t = this._terms();
    if (!t) { return false; }
    this._accepting.set(true);
    this._error.set(null);
    try {
      const res = await firstValueFrom(this.api.accept(t.tos_version, t.privacy_version));
      if (res.error) { this._error.set(res.error); return false; }
      this._terms.set({ ...t, needs_acceptance: false });
      return true;
    } catch (e) {
      const err = (e as { appError?: { apiError?: ApiError } })?.appError?.apiError;
      // Stale versions: refresh so the modal reflects the current ones.
      if (err?.code === 'TERMS_VERSION_MISMATCH') {
        await this.load();
      }
      this._error.set(err ?? { code: 'UNKNOWN', message: 'An unexpected error occurred.' });
      return false;
    } finally {
      this._accepting.set(false);
    }
  }
}
