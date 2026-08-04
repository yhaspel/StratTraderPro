/** Signal-based store for the M08 risk feature — profile, active kill switches,
 *  risk events, and sizing decisions. */
import { Injectable, computed, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import {
  KillSwitch,
  RiskEvent,
  RiskProfile,
  SizingDecision,
} from '../../core/models/risk.models';

@Injectable({ providedIn: 'root' })
export class RiskStore {
  private readonly _profile = signal<RiskProfile | null>(null);
  private readonly _killswitches = signal<KillSwitch[]>([]);
  private readonly _events = signal<RiskEvent[]>([]);
  private readonly _sizingDecisions = signal<SizingDecision[]>([]);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly profile = this._profile.asReadonly();
  readonly killswitches = this._killswitches.asReadonly();
  readonly events = this._events.asReadonly();
  readonly sizingDecisions = this._sizingDecisions.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  /** True when any kill switch is currently active. */
  readonly haltActive = computed(() => this._killswitches().length > 0);

  setLoading(loading: boolean) { this._loading.set(loading); }
  setError(err: ApiError | null) { this._error.set(err); }

  setProfile(profile: RiskProfile | null) { this._profile.set(profile); }
  setKillswitches(switches: KillSwitch[]) { this._killswitches.set(switches); }
  setEvents(events: RiskEvent[]) { this._events.set(events); }
  setSizingDecisions(decisions: SizingDecision[]) { this._sizingDecisions.set(decisions); }
}
