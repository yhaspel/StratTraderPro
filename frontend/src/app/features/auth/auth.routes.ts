import { Routes } from '@angular/router';
import { guestGuard } from '../../core/guards/guest.guard';

export const AUTH_ROUTES: Routes = [
  {
    path: 'login',
    canMatch: [guestGuard],
    loadComponent: () => import('./login/login.component').then(m => m.LoginComponent),
  },
  {
    // /login/mfa — MFA challenge step. NOT guest-guarded: it's reachable
    // *only* when AuthStore holds an mfa_token; the component itself
    // bounces back to /login if there's no token.
    path: 'login/mfa',
    loadComponent: () => import('./mfa-challenge/mfa-challenge.component').then(m => m.MfaChallengeComponent),
  },
  {
    path: 'register',
    canMatch: [guestGuard],
    loadComponent: () => import('./register/register.component').then(m => m.RegisterComponent),
  },
  {
    path: 'verify-email',
    loadComponent: () => import('./verify-email/verify-email.component').then(m => m.VerifyEmailComponent),
  },
  {
    path: 'resend-verification',
    loadComponent: () => import('./resend-verification/resend-verification.component').then(m => m.ResendVerificationComponent),
  },
  {
    path: 'password-reset',
    canMatch: [guestGuard],
    loadComponent: () => import('./password-reset/password-reset.component').then(m => m.PasswordResetComponent),
  },
  {
    path: 'password-reset/confirm',
    loadComponent: () => import('./password-reset-confirm/password-reset-confirm.component').then(m => m.PasswordResetConfirmComponent),
  },
];
