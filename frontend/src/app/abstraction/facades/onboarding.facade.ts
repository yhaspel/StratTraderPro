/** Onboarding facade (M10.5 §7.3) — signal-backed getting-started state. */
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { OnboardingApi } from '../../core/services/onboarding.api';
import { OnboardingStatus } from '../../core/models/onboarding.models';

@Injectable({ providedIn: 'root' })
export class OnboardingFacade {
  private api = inject(OnboardingApi);

  private readonly _status = signal<OnboardingStatus | null>(null);
  private readonly _loading = signal(false);
  readonly status = this._status.asReadonly();
  readonly loading = this._loading.asReadonly();

  /** True once loaded AND at least one step is still incomplete — the shell's
   * "Getting started" nav item + the dashboard empty state key off this. */
  readonly incomplete = computed(() => {
    const s = this._status();
    return s !== null && !s.complete;
  });

  async load(): Promise<void> {
    this._loading.set(true);
    try {
      const res = await firstValueFrom(this.api.getStatus());
      if (res.data) { this._status.set(res.data); }
    } catch {
      // Best-effort: the checklist/nav item simply stays hidden on failure.
    } finally {
      this._loading.set(false);
    }
  }
}
