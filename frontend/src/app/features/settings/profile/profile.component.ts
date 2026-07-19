/**
 * /settings/profile — display name, timezone (searchable IANA dropdown),
 * language, email-notification toggle. "Industry" design system.
 */
import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { ProfileFacade } from '../../../abstraction/facades/profile.facade';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    TranslateModule,
    ButtonComponent,
    CardComponent,
    PageHeaderComponent,
  ],
  template: `
    <div class="mx-auto max-w-2xl p-6">
      <app-page-header [heading]="'profile.title' | translate" />

      @if (profile.error(); as err) {
        <div class="mb-s3 rounded-none border border-down bg-down-tint px-4 py-3 text-sm text-down-deep" role="alert">
          {{ err.message }}
        </div>
      }
      @if (saved()) {
        <div class="mb-s3 rounded-none border border-divider bg-accent-100 px-4 py-3 text-sm text-accent-800" role="status">
          ✓ {{ 'profile.saved' | translate }}
        </div>
      }

      <app-card>
        <form [formGroup]="form" (ngSubmit)="onSubmit()" class="max-w-lg space-y-s4">
          <div>
            <label class="mb-1 block text-xs font-medium text-neutral-600" for="display_name">
              {{ 'profile.display_name' | translate }}
            </label>
            <input
              id="display_name"
              type="text"
              formControlName="display_name"
              class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
            />
          </div>

          <div>
            <label class="mb-1 block text-xs font-medium text-neutral-600" for="timezone">
              {{ 'profile.timezone' | translate }}
            </label>
            <input
              id="tz_search"
              type="search"
              [placeholder]="'profile.timezone_search' | translate"
              (input)="filterTimezones($any($event.target).value)"
              class="mb-2 w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none"
            />
            <select
              id="timezone"
              formControlName="timezone"
              class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-accent focus:outline-none"
              size="6"
            >
              @for (tz of filteredTimezones(); track tz) {
                <option [value]="tz">{{ tz }}</option>
              }
            </select>
          </div>

          <div>
            <label class="mb-1 block text-xs font-medium text-neutral-600" for="language">
              {{ 'profile.language' | translate }}
            </label>
            <select id="language" formControlName="language"
                    class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none">
              <option value="en">English</option>
            </select>
            <p class="mt-1 text-[11px] text-neutral-600">{{ 'profile.language_hint' | translate }}</p>
          </div>

          <label class="flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" formControlName="notification_email"
                   class="h-[15px] w-[15px] rounded-none accent-accent" />
            <span>{{ 'profile.notification_email' | translate }}</span>
          </label>

          <app-button
            type="submit"
            variant="primary"
            [disabled]="form.invalid || profile.loading()"
          >
            {{ 'common.save' | translate }}
          </app-button>
        </form>
      </app-card>
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
