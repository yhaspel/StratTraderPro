/** Signal-based store for the M06 market-data regime.
 *
 * Holds the latest observation, the recent history feed (most-recent first, as
 * returned by the API), the active model descriptor, plus loading/error flags. */
import { Injectable, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import { RegimeModelInfo, RegimeObservation } from '../../core/models/regime.models';

@Injectable({ providedIn: 'root' })
export class RegimeStore {
  private readonly _current = signal<RegimeObservation | null>(null);
  private readonly _history = signal<RegimeObservation[]>([]);
  private readonly _model = signal<RegimeModelInfo | null>(null);
  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly current = this._current.asReadonly();
  readonly history = this._history.asReadonly();
  readonly model = this._model.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  setCurrent(observation: RegimeObservation | null) { this._current.set(observation); }
  setHistory(observations: RegimeObservation[]) { this._history.set(observations); }
  setModel(model: RegimeModelInfo | null) { this._model.set(model); }
  setLoading(loading: boolean) { this._loading.set(loading); }
  setError(err: ApiError | null) { this._error.set(err); }

  reset() {
    this._current.set(null);
    this._history.set([]);
    this._model.set(null);
    this._error.set(null);
  }
}
