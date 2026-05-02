/**
 * "Continue with Google" button. Brand-compliant per Google's Identity
 * Branding Guidelines (white background, Google G logo, Roboto/system font,
 * 40px min height).
 *
 * Used on /login and /register. Click triggers facade.startGoogleSignIn(),
 * which fetches the authorize URL from the backend and redirects.
 */
import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

@Component({
  selector: 'app-google-button',
  standalone: true,
  imports: [CommonModule, TranslateModule],
  template: `
    <button
      type="button"
      (click)="onClick()"
      [disabled]="facade.status() === 'loading'"
      class="w-full flex items-center justify-center gap-3 border border-gray-300 bg-white text-gray-700 px-4 py-2 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition"
    >
      <!-- Google G logo (Google brand SVG; permitted use per their branding guidelines) -->
      <svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
        <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
        <path d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
        <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
      </svg>
      <span class="text-sm font-medium">{{ 'oauth.continue_with_google' | translate }}</span>
    </button>
  `,
})
export class GoogleButtonComponent {
  facade = inject(AuthFacade);

  async onClick(): Promise<void> {
    await this.facade.startGoogleSignIn();
  }
}
