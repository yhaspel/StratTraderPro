/** Signal-based store for the M10 Admin Portal — a server-paginated users list,
 *  the selected user detail, a server-paginated audit feed with its filters, the
 *  feature-flag registry, the platform health snapshot + kill-switch status, and
 *  the active impersonation session (drives the persistent banner). */
import { Injectable, computed, signal } from '@angular/core';
import { ApiError } from '../../core/models/auth.models';
import {
  AdminHealth,
  AdminMeta,
  AdminUserDetail,
  AdminUserListParams,
  AdminUserRow,
  AuditFilters,
  AuditRow,
  FeatureFlag,
  ImpersonationSession,
  PlatformStatus,
} from '../../core/models/admin.models';

@Injectable({ providedIn: 'root' })
export class AdminStore {
  private readonly _users = signal<AdminUserRow[]>([]);
  private readonly _usersMeta = signal<AdminMeta | null>(null);
  private readonly _userFilters = signal<AdminUserListParams>({});
  private readonly _selectedUser = signal<AdminUserDetail | null>(null);

  private readonly _audit = signal<AuditRow[]>([]);
  private readonly _auditMeta = signal<AdminMeta | null>(null);
  private readonly _auditFilters = signal<AuditFilters>({});

  private readonly _flags = signal<FeatureFlag[]>([]);
  private readonly _health = signal<AdminHealth | null>(null);
  private readonly _platform = signal<PlatformStatus | null>(null);
  private readonly _impersonation = signal<ImpersonationSession | null>(null);

  private readonly _loading = signal(false);
  private readonly _error = signal<ApiError | null>(null);

  readonly users = this._users.asReadonly();
  readonly usersMeta = this._usersMeta.asReadonly();
  readonly userFilters = this._userFilters.asReadonly();
  readonly selectedUser = this._selectedUser.asReadonly();

  readonly audit = this._audit.asReadonly();
  readonly auditMeta = this._auditMeta.asReadonly();
  readonly auditFilters = this._auditFilters.asReadonly();

  readonly flags = this._flags.asReadonly();
  readonly health = this._health.asReadonly();
  readonly platform = this._platform.asReadonly();
  readonly impersonation = this._impersonation.asReadonly();

  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  readonly usersPage = computed(() => this._usersMeta()?.page ?? 1);
  readonly usersTotalPages = computed(() => this._usersMeta()?.total_pages ?? 0);
  readonly usersTotal = computed(() => this._usersMeta()?.total ?? 0);

  readonly auditPage = computed(() => this._auditMeta()?.page ?? 1);
  readonly auditTotalPages = computed(() => this._auditMeta()?.total_pages ?? 0);
  readonly auditTotal = computed(() => this._auditMeta()?.total ?? 0);

  readonly platformHalted = computed(() => this._platform()?.platform_halted ?? false);
  readonly isImpersonating = computed(() => this._impersonation() !== null);

  // --- Mutations ---

  setLoading(loading: boolean): void { this._loading.set(loading); }
  setError(err: ApiError | null): void { this._error.set(err); }

  setUserFilters(filters: AdminUserListParams): void { this._userFilters.set(filters); }
  setUsersPage(users: AdminUserRow[], meta: AdminMeta | null): void {
    this._users.set(users);
    this._usersMeta.set(meta);
  }
  setSelectedUser(user: AdminUserDetail | null): void { this._selectedUser.set(user); }

  /** Reflect an active-state change on the selected detail + any matching list row. */
  patchUserActive(id: string, isActive: boolean): void {
    const sel = this._selectedUser();
    if (sel && sel.id === id) { this._selectedUser.set({ ...sel, is_active: isActive }); }
    const rows = this._users();
    if (rows.some(r => r.id === id)) {
      this._users.set(rows.map(r => (r.id === id ? { ...r, is_active: isActive } : r)));
    }
  }

  setAuditFilters(filters: AuditFilters): void { this._auditFilters.set(filters); }
  setAuditPage(rows: AuditRow[], meta: AdminMeta | null): void {
    this._audit.set(rows);
    this._auditMeta.set(meta);
  }

  setFlags(flags: FeatureFlag[]): void { this._flags.set(flags); }
  /** Replace a single flag in-place after a toggle. */
  patchFlag(flag: FeatureFlag): void {
    this._flags.set(this._flags().map(f => (f.name === flag.name ? flag : f)));
  }

  setHealth(health: AdminHealth | null): void { this._health.set(health); }
  setPlatform(status: PlatformStatus | null): void { this._platform.set(status); }
  setImpersonation(session: ImpersonationSession | null): void { this._impersonation.set(session); }
}
