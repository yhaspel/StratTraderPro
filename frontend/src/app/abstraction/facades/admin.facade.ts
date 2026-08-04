/** AdminFacade — bridges the AdminApi + AdminStore + UI (M10 Admin Portal).
 *
 * Exposes the store signals for templates and orchestrates the async calls with
 * `firstValueFrom`, funnelling failures through `_asError` (same shape as
 * BacktestFacade). Mutating actions (disable/enable, killswitch, flag toggle,
 * impersonation) return a `Result<T>` so components can keep an inline MFA
 * prompt open and render the specific error code on failure. CSV export uses the
 * transient object-URL blob pattern (mirrors OrdersFacade.exportCsv).
 */
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError } from '../../core/models/auth.models';
import {
  AdminUserActionBody,
  AdminUserListParams,
  AuditFilters,
  DisableResult,
  EnableResult,
  FeatureFlag,
  FlagToggleBody,
  ImpersonationSession,
  KillswitchBody,
  PlatformStatus,
} from '../../core/models/admin.models';
import { AdminApi } from '../../core/services/admin.api';
import { AdminStore } from '../stores/admin.store';

type Result<T> = { ok: true; value: T } | { ok: false; error: ApiError };

@Injectable({ providedIn: 'root' })
export class AdminFacade {
  private api = inject(AdminApi);
  private store = inject(AdminStore);

  readonly users = this.store.users;
  readonly usersMeta = this.store.usersMeta;
  readonly userFilters = this.store.userFilters;
  readonly selectedUser = this.store.selectedUser;
  readonly usersPage = this.store.usersPage;
  readonly usersTotalPages = this.store.usersTotalPages;
  readonly usersTotal = this.store.usersTotal;

  readonly audit = this.store.audit;
  readonly auditMeta = this.store.auditMeta;
  readonly auditFilters = this.store.auditFilters;
  readonly auditPage = this.store.auditPage;
  readonly auditTotalPages = this.store.auditTotalPages;
  readonly auditTotal = this.store.auditTotal;

  readonly flags = this.store.flags;
  readonly health = this.store.health;
  readonly platform = this.store.platform;
  readonly platformHalted = this.store.platformHalted;
  readonly impersonation = this.store.impersonation;
  readonly isImpersonating = this.store.isImpersonating;

  readonly loading = this.store.loading;
  readonly error = this.store.error;

  // ---- Users ----

  /** Load a page. Omitting ``filters`` reuses the last-applied set (paging). */
  async loadUsers(page = 1, filters?: AdminUserListParams): Promise<void> {
    const active = filters ?? this.store.userFilters();
    this.store.setUserFilters(active);
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.listUsers({ ...active, page }));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setUsersPage(res.data ?? [], res.meta ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async openUser(id: string): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    this.store.setSelectedUser(null);
    try {
      const res = await firstValueFrom(this.api.getUser(id));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setSelectedUser(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async disableUser(id: string, body: AdminUserActionBody): Promise<Result<DisableResult>> {
    try {
      const res = await firstValueFrom(this.api.disableUser(id, body));
      if (res.error) { return { ok: false, error: res.error }; }
      this.store.patchUserActive(id, res.data!.is_active);
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  async enableUser(id: string, body: AdminUserActionBody): Promise<Result<EnableResult>> {
    try {
      const res = await firstValueFrom(this.api.enableUser(id, body));
      if (res.error) { return { ok: false, error: res.error }; }
      this.store.patchUserActive(id, res.data!.is_active);
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  // ---- Impersonation ----

  async startImpersonation(id: string, body: AdminUserActionBody): Promise<Result<ImpersonationSession>> {
    try {
      const res = await firstValueFrom(this.api.startImpersonation(id, body));
      if (res.error) { return { ok: false, error: res.error }; }
      this.store.setImpersonation(res.data!);
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  async stopImpersonation(): Promise<Result<void>> {
    const session = this.store.impersonation();
    if (!session) { return { ok: true, value: undefined }; }
    try {
      const res = await firstValueFrom(this.api.stopImpersonation(session.session_id));
      if (res.error) { return { ok: false, error: res.error }; }
      this.store.setImpersonation(null);
      return { ok: true, value: undefined };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  // ---- Audit ----

  async loadAudit(page = 1, filters?: AuditFilters): Promise<void> {
    const active = filters ?? this.store.auditFilters();
    this.store.setAuditFilters(active);
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.listAudit({ ...active, page }));
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setAuditPage(res.data ?? [], res.meta ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  /** Set the active audit filters (from the form) then export the matching CSV. */
  setAuditFiltersAndExport(filters: AuditFilters): void {
    this.store.setAuditFilters(filters);
    void this.exportAuditCsv();
  }

  /** Download the filtered audit set as a CSV file via a transient object URL. */
  async exportAuditCsv(): Promise<void> {
    try {
      const blob = await firstValueFrom(this.api.exportAuditCsv(this.store.auditFilters()));
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'audit.csv';
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  // ---- Platform kill switch ----

  async loadPlatformStatus(): Promise<void> {
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.platformStatus());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setPlatform(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    }
  }

  async killswitch(body: KillswitchBody): Promise<Result<PlatformStatus>> {
    try {
      const res = await firstValueFrom(this.api.killswitch(body));
      if (res.error) { return { ok: false, error: res.error }; }
      this.store.setPlatform(res.data ?? null);
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  // ---- Feature flags ----

  async loadFlags(): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.listFlags());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setFlags(res.data ?? []);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  async toggleFlag(name: string, body: FlagToggleBody): Promise<Result<FeatureFlag>> {
    try {
      const res = await firstValueFrom(this.api.toggleFlag(name, body));
      if (res.error) { return { ok: false, error: res.error }; }
      this.store.patchFlag(res.data!);
      return { ok: true, value: res.data! };
    } catch (err) {
      return { ok: false, error: this._asError(err) };
    }
  }

  // ---- Health ----

  async loadHealth(): Promise<void> {
    this.store.setLoading(true);
    this.store.setError(null);
    try {
      const res = await firstValueFrom(this.api.health());
      if (res.error) { this.store.setError(res.error); return; }
      this.store.setHealth(res.data ?? null);
    } catch (err) {
      this.store.setError(this._asError(err));
    } finally {
      this.store.setLoading(false);
    }
  }

  private _asError(err: unknown): ApiError {
    const wrapped = err as { appError?: { apiError?: ApiError; message?: string }; message?: string };
    if (wrapped?.appError?.apiError?.code) {
      return wrapped.appError.apiError;
    }
    return {
      code: 'UNKNOWN',
      message: wrapped?.appError?.message ?? wrapped?.message ?? 'Unknown error',
    };
  }
}
