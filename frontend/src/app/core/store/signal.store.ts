import { Injectable, inject, computed } from '@angular/core';
import { AuthStore } from '../../abstraction/stores/auth.store';

/**
 * Root signal store — aggregates feature stores for cross-cutting reads.
 * Auth state now lives in AuthStore; this re-exports computed signals
 * for convenience in templates that import SignalStore.
 */
@Injectable({ providedIn: 'root' })
export class SignalStore {
  private auth = inject(AuthStore);

  readonly currentUser = this.auth.user;
  readonly isAuthenticated = this.auth.isAuthenticated;
}
