import { TestBed } from '@angular/core/testing';
import { AuthStore } from './auth.store';
import { AuthUser } from '../../core/models/auth.models';

const REFRESH_KEY = 'stp_refresh_token';

const mockUser: AuthUser = {
  id: 'uuid-001',
  email: 'trader@example.com',
  display_name: 'Test Trader',
  is_verified: true,
};

describe('AuthStore', () => {
  let store: AuthStore;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    store = TestBed.inject(AuthStore);
  });

  afterEach(() => localStorage.clear());

  it('starts in idle state with no user or tokens', () => {
    expect(store.status()).toBe('idle');
    expect(store.user()).toBeNull();
    expect(store.accessToken()).toBeNull();
    expect(store.isAuthenticated()).toBeFalse();
  });

  it('setLoading() transitions to loading and clears error', () => {
    store.setError({ code: 'INVALID_CREDENTIALS', message: 'bad' });
    store.setLoading();
    expect(store.status()).toBe('loading');
    expect(store.error()).toBeNull();
  });

  it('setAuthed() sets user, tokens, and status; persists refresh to localStorage', () => {
    store.setAuthed(mockUser, 'access-tok', 'refresh-tok');
    expect(store.status()).toBe('authed');
    expect(store.user()).toEqual(mockUser);
    expect(store.accessToken()).toBe('access-tok');
    expect(store.refreshToken()).toBe('refresh-tok');
    expect(store.isAuthenticated()).toBeTrue();
    expect(localStorage.getItem(REFRESH_KEY)).toBe('refresh-tok');
  });

  it('setError() transitions to error state', () => {
    const err = { code: 'ACCOUNT_LOCKED', message: 'Locked.' };
    store.setError(err);
    expect(store.status()).toBe('error');
    expect(store.error()).toEqual(err);
    expect(store.isAuthenticated()).toBeFalse();
  });

  it('clearAuth() wipes all state and removes localStorage key', () => {
    store.setAuthed(mockUser, 'a', 'r');
    store.clearAuth();
    expect(store.status()).toBe('idle');
    expect(store.user()).toBeNull();
    expect(store.accessToken()).toBeNull();
    expect(store.refreshToken()).toBeNull();
    expect(store.isAuthenticated()).toBeFalse();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it('updateTokens() replaces tokens and persists new refresh', () => {
    store.setAuthed(mockUser, 'old-access', 'old-refresh');
    store.updateTokens('new-access', 'new-refresh');
    expect(store.accessToken()).toBe('new-access');
    expect(store.refreshToken()).toBe('new-refresh');
    expect(localStorage.getItem(REFRESH_KEY)).toBe('new-refresh');
  });

  it('loads persisted refresh token from localStorage on construction', () => {
    localStorage.setItem(REFRESH_KEY, 'persisted-refresh');
    // Re-create store to simulate page reload
    const freshStore = new AuthStore();
    expect(freshStore.refreshToken()).toBe('persisted-refresh');
  });

  it('isAuthenticated is false when status is loading even if user is set', () => {
    store.setAuthed(mockUser, 'a', 'r');
    store.setLoading();
    expect(store.isAuthenticated()).toBeFalse();
  });
});
