/** Auth domain types — aligned with backend API envelope. */

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  is_verified: boolean;
}

export interface AuthTokenPair {
  access: string;
  refresh: string;
  user: AuthUser;
  mfa_required?: boolean;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, string[]>;
}

export interface ApiEnvelope<T> {
  data?: T;
  error?: ApiError;
}

export type AuthStatus = 'idle' | 'loading' | 'error' | 'authed';
