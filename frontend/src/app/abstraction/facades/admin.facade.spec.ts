import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { AdminFacade } from './admin.facade';
import { AdminApi } from '../../core/services/admin.api';
import { FeatureFlag, ImpersonationSession, PlatformStatus } from '../../core/models/admin.models';

describe('AdminFacade', () => {
  let facade: AdminFacade;
  let api: jasmine.SpyObj<AdminApi>;

  beforeEach(() => {
    api = jasmine.createSpyObj('AdminApi', [
      'listUsers', 'getUser', 'disableUser', 'enableUser',
      'startImpersonation', 'stopImpersonation', 'listAudit', 'exportAuditCsv',
      'platformStatus', 'killswitch', 'listFlags', 'toggleFlag', 'health',
    ]);

    TestBed.configureTestingModule({
      providers: [
        AdminFacade,
        { provide: AdminApi, useValue: api },
      ],
    });
    facade = TestBed.inject(AdminFacade);
  });

  it('loadUsers stores the page + meta from the envelope', async () => {
    api.listUsers.and.returnValue(of({
      data: [{
        id: 'u1', email: 'a@b.com', display_name: 'A', is_active: true, is_staff: false,
        is_verified: true, mfa_enabled: false, created_at: '2026-01-01T00:00:00Z', broker_count: 2,
      }],
      meta: { page: 1, page_size: 25, total: 1, total_pages: 1 },
    }));

    await facade.loadUsers(1, { q: 'a' });

    expect(api.listUsers).toHaveBeenCalledWith({ q: 'a', page: 1 });
    expect(facade.users().length).toBe(1);
    expect(facade.usersTotal()).toBe(1);
  });

  it('disableUser returns ok and patches the active state', async () => {
    api.disableUser.and.returnValue(of({
      data: { id: 'u1', is_active: false, families_revoked: 3, note: 'done' },
    }));

    const res = await facade.disableUser('u1', { mfa_code: '123456', reason: 'abuse' });

    expect(res.ok).toBeTrue();
    if (res.ok) { expect(res.value.families_revoked).toBe(3); }
  });

  it('disableUser surfaces an API error envelope', async () => {
    api.disableUser.and.returnValue(of({ error: { code: 'MFA_REQUIRED', message: 'bad code' } }));

    const res = await facade.disableUser('u1', { mfa_code: '000000', reason: '' });

    expect(res.ok).toBeFalse();
    if (!res.ok) { expect(res.error.code).toBe('MFA_REQUIRED'); }
  });

  it('startImpersonation stores the session so the banner shows', async () => {
    const session: ImpersonationSession = { token: 't', session_id: 's1', expires_at: '2026-01-01T00:05:00Z' };
    api.startImpersonation.and.returnValue(of({ data: session }));

    const res = await facade.startImpersonation('u1', { mfa_code: '123456', reason: 'debug' });

    expect(res.ok).toBeTrue();
    expect(facade.isImpersonating()).toBeTrue();
    expect(facade.impersonation()?.session_id).toBe('s1');
  });

  it('stopImpersonation clears the active session', async () => {
    const session: ImpersonationSession = { token: 't', session_id: 's1', expires_at: '2026-01-01T00:05:00Z' };
    api.startImpersonation.and.returnValue(of({ data: session }));
    await facade.startImpersonation('u1', { mfa_code: '123456', reason: '' });

    api.stopImpersonation.and.returnValue(of({ data: { session_id: 's1', stopped: true, ended_at: 'now' } }));
    const res = await facade.stopImpersonation();

    expect(res.ok).toBeTrue();
    expect(api.stopImpersonation).toHaveBeenCalledWith('s1');
    expect(facade.isImpersonating()).toBeFalse();
  });

  it('killswitch stores the returned platform status', async () => {
    const status: PlatformStatus = { platform_halted: true, halt: null, note: '' };
    api.killswitch.and.returnValue(of({ data: status }));

    const res = await facade.killswitch({ engage: true, reason: 'x', mfa_code: '123456', confirm: 'HALT PLATFORM' });

    expect(res.ok).toBeTrue();
    expect(facade.platformHalted()).toBeTrue();
  });

  it('toggleFlag replaces the flag in the store', async () => {
    const flag: FeatureFlag = { name: 'x', enabled: false, source: 'db', mutable: true, dangerous: false, description: '', default: false };
    api.listFlags.and.returnValue(of({ data: [flag] }));
    await facade.loadFlags();

    api.toggleFlag.and.returnValue(of({ data: { ...flag, enabled: true } }));
    const res = await facade.toggleFlag('x', { enabled: true, mfa_code: '123456' });

    expect(res.ok).toBeTrue();
    expect(facade.flags()[0].enabled).toBeTrue();
  });

  it('exportAuditCsv pulls the blob and clicks a transient anchor', async () => {
    api.exportAuditCsv.and.returnValue(of(new Blob(['id,event'], { type: 'text/csv' })));
    const anchor = document.createElement('a');
    spyOn(anchor, 'click');
    spyOn(document, 'createElement').and.returnValue(anchor);
    spyOn(URL, 'createObjectURL').and.returnValue('blob:mock');
    spyOn(URL, 'revokeObjectURL');

    await facade.exportAuditCsv();

    expect(api.exportAuditCsv).toHaveBeenCalled();
    expect(anchor.click).toHaveBeenCalled();
    expect(anchor.download).toBe('audit.csv');
  });
});
