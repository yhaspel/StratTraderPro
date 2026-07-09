import { TestBed } from '@angular/core/testing';
import { AdminStore } from './admin.store';
import {
  AdminMeta,
  AdminUserDetail,
  AdminUserRow,
  FeatureFlag,
  ImpersonationSession,
  PlatformStatus,
} from '../../core/models/admin.models';

function userRow(overrides: Partial<AdminUserRow> = {}): AdminUserRow {
  return {
    id: 'u1', email: 'a@b.com', display_name: 'A',
    is_active: true, is_staff: false, is_verified: true, mfa_enabled: false,
    created_at: '2026-01-01T00:00:00Z', broker_count: 0, ...overrides,
  };
}

const meta: AdminMeta = { page: 1, page_size: 25, total: 1, total_pages: 1 };

describe('AdminStore', () => {
  let store: AdminStore;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    store = TestBed.inject(AdminStore);
  });

  it('setUsersPage populates users + derived pagination signals', () => {
    store.setUsersPage([userRow()], meta);
    expect(store.users().length).toBe(1);
    expect(store.usersPage()).toBe(1);
    expect(store.usersTotalPages()).toBe(1);
    expect(store.usersTotal()).toBe(1);
  });

  it('patchUserActive updates both the list row and the selected detail', () => {
    store.setUsersPage([userRow({ id: 'u1', is_active: true })], meta);
    const detail: AdminUserDetail = { ...userRow({ id: 'u1', is_active: true }), brokers: [], recent_audit: [] };
    store.setSelectedUser(detail);

    store.patchUserActive('u1', false);

    expect(store.users()[0].is_active).toBeFalse();
    expect(store.selectedUser()?.is_active).toBeFalse();
  });

  it('patchUserActive leaves non-matching rows untouched', () => {
    store.setUsersPage([userRow({ id: 'u1' }), userRow({ id: 'u2' })], meta);
    store.patchUserActive('u2', false);
    expect(store.users()[0].is_active).toBeTrue();
    expect(store.users()[1].is_active).toBeFalse();
  });

  it('patchFlag replaces the matching flag in place', () => {
    const flags: FeatureFlag[] = [
      { name: 'x', enabled: false, source: 'db', mutable: true, dangerous: false, description: '', default: false },
      { name: 'y', enabled: true, source: 'db', mutable: true, dangerous: false, description: '', default: true },
    ];
    store.setFlags(flags);
    store.patchFlag({ ...flags[0], enabled: true });
    expect(store.flags()[0].enabled).toBeTrue();
    expect(store.flags()[1].enabled).toBeTrue();
  });

  it('tracks platform halted state', () => {
    const status: PlatformStatus = { platform_halted: true, halt: null, note: 'op halt' };
    store.setPlatform(status);
    expect(store.platformHalted()).toBeTrue();
  });

  it('tracks an active impersonation session', () => {
    expect(store.isImpersonating()).toBeFalse();
    const session: ImpersonationSession = { token: 't', session_id: 's1', expires_at: '2026-01-01T00:05:00Z' };
    store.setImpersonation(session);
    expect(store.isImpersonating()).toBeTrue();
    store.setImpersonation(null);
    expect(store.isImpersonating()).toBeFalse();
  });
});
