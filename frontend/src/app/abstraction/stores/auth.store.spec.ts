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

  it('setAuthed() sets user + access token and status (no refresh in JS)', () => {
    store.setAuthed(mockUser, 'access-tok');
    expect(store.status()).toBe('authed');
    expect(store.user()).toEqual(mockUser);
    expect(store.accessToken()).toBe('access-tok');
    expect(store.isAuthenticated()).toBeTrue();
    // P1-4: the refresh token is an HttpOnly cookie — never in localStorage.
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it('setError() transitions to error state', () => {
    const err = { code: 'ACCOUNT_LOCKED', message: 'Locked.' };
    store.setError(err);
    expect(store.status()).toBe('error');
    expect(store.error()).toEqual(err);
    expect(store.isAuthenticated()).toBeFalse();
  });

  it('clearAuth() wipes all state', () => {
    store.setAuthed(mockUser, 'a');
    store.clearAuth();
    expect(store.status()).toBe('idle');
    expect(store.user()).toBeNull();
    expect(store.accessToken()).toBeNull();
    expect(store.isAuthenticated()).toBeFalse();
  });

  it('updateTokens() replaces the access token', () => {
    store.setAuthed(mockUser, 'old-access');
    store.updateTokens('new-access');
    expect(store.accessToken()).toBe('new-access');
  });

  it('purges any legacy refresh token from localStorage on construction (P1-4)', () => {
    localStorage.setItem(REFRESH_KEY, 'stale-refresh');
    // Re-create store to simulate page reload.
    new AuthStore();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it('isAuthenticated is false when status is loading even if user is set', () => {
    store.setAuthed(mockUser, 'a');
    store.setLoading();
    expect(store.isAuthenticated()).toBeFalse();
  });
});
