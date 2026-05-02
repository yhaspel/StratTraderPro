/**
 * /settings/profile — display name, timezone (searchable IANA dropdown),
 * language, email-notification toggle.
 */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { ProfileFacade } from '../../../abstraction/facades/profile.facade';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, TranslateModule],
  template: `
    <div class="mx-auto max-w-2xl p-6">
      <h1 class="text-2xl font-bold mb-6">{{ 'profile.title' | translate }}</h1>

      @if (profile.error(); as err) {
        <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4" role="alert">
          {{ err.message }}
        </div>
      }
      @if (saved()) {
        <div class="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded mb-4" role="status">
          ✓ {{ 'profile.saved' | translate }}
        </div>
      }

      <form [formGroup]="form" (ngSubmit)="onSubmit()" class="space-y-4 max-w-lg">
        <div>
          <label class="block text-sm font-medium mb-1" for="display_name">
            {{ 'profile.display_name' | translate }}
          </label>
          <input
            id="display_name"
            type="text"
            formControlName="display_name"
            class="w-full border rounded px-3 py-2"
          />
        </div>

        <div>
          <label class="block text-sm font-medium mb-1" for="timezone">
            {{ 'profile.timezone' | translate }}
          </label>
          <input
            id="tz_search"
            type="search"
            [placeholder]="'profile.timezone_search' | translate"
            (input)="filterTimezones($any($event.target).value)"
            class="w-full border rounded px-3 py-2 mb-2"
          />
          <select
            id="timezone"
            formControlName="timezone"
            class="w-full border rounded px-3 py-2"
            size="6"
          >
            @for (tz of filteredTimezones(); track tz) {
              <option [value]="tz">{{ tz }}</option>
            }
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium mb-1" for="language">
            {{ 'profile.language' | translate }}
          </label>
          <select id="language" formControlName="language" class="w-full border rounded px-3 py-2">
            <option value="en">English</option>
          </select>
          <p class="text-xs text-gray-500 mt-1">{{ 'profile.language_hint' | translate }}</p>
        </div>

        <label class="flex items-center gap-2">
          <input type="checkbox" formControlName="notification_email" />
          <span>{{ 'profile.notification_email' | translate }}</span>
        </label>

        <button
          type="submit"
          class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          [disabled]="form.invalid || profile.loading()"
        >
          {{ 'common.save' | translate }}
        </button>
      </form>
    </div>
  `,
})
export class ProfileComponent implements OnInit {
  profile = inject(ProfileFacade);
  auth = inject(AuthFacade);
  private fb = inject(FormBuilder);

  saved = signal(false);
  allTimezones = signal<string[]>([]);
  filteredTimezones = signal<string[]>([]);

  form = this.fb.nonNullable.group({
    display_name: ['', [Validators.required, Validators.maxLength(64)]],
    timezone: ['America/New_York', Validators.required],
    language: ['en', Validators.required],
    notification_email: [true],
  });

  async ngOnInit(): Promise<void> {
    // Locale-aware IANA timezone list, falls back to a small static list
    // on browsers that don't support Intl.supportedValuesOf().
    const fn = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
    const tzs = fn ? fn('timeZone') : [
      'UTC', 'America/New_York', 'America/Los_Angeles', 'America/Chicago',
      'Europe/London', 'Europe/Paris', 'Asia/Tokyo', 'Asia/Singapore',
    ];
    this.allTimezones.set(tzs);
    this.filteredTimezones.set(tzs.slice(0, 100));

    await this.profile.load();
    const p = this.profile.profile();
    const u = this.auth.user();
    this.form.patchValue({
      display_name: u?.display_name ?? '',
      timezone: p?.timezone ?? 'America/New_York',
      language: p?.language ?? 'en',
      notification_email: p?.notification_email ?? true,
    });
  }

  filterTimezones(query: string): void {
    const q = query.toLowerCase().trim();
    if (!q) {
      this.filteredTimezones.set(this.allTimezones().slice(0, 100));
      return;
    }
    this.filteredTimezones.set(
      this.allTimezones().filter(tz => tz.toLowerCase().includes(q)).slice(0, 200),
    );
  }

  async onSubmit(): Promise<void> {
    if (this.form.invalid) return;
    this.saved.set(false);
    const ok = await this.profile.update(this.form.getRawValue());
    if (ok) {
      this.saved.set(true);
      setTimeout(() => this.saved.set(false), 3000);
    }
  }
}
