/**
 * /settings/profile — display name, timezone (searchable IANA dropdown),
 * language, email-notification toggle. "Industry" design system.
 */
import { Component, ElementRef, OnInit, ViewChild, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import { ProfileFacade } from '../../../abstraction/facades/profile.facade';
import { ButtonComponent } from '../../shared/ui/button.component';
import { CardComponent } from '../../shared/ui/card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';

/** Browsers without `Intl.supportedValuesOf` (older Safari) get this. */
const FALLBACK_TIMEZONES = [
  'UTC', 'America/New_York', 'America/Los_Angeles', 'America/Chicago',
  'Europe/London', 'Europe/Paris', 'Asia/Jerusalem', 'Asia/Tokyo', 'Asia/Singapore',
];

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
            <label class="mb-1 block text-xs font-medium text-neutral-700" for="display_name">
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
            <label class="mb-1 block text-xs font-medium text-neutral-700" for="timezone">
              {{ 'profile.timezone' | translate }}
            </label>

            <!-- Current selection, spelled out. The <select size="6"> alone was
                 not enough of an answer to "what is my timezone set to?" — when
                 the value sat outside the visible six rows there was nothing
                 on screen that named it. -->
            <p class="mb-2 text-[13px] text-neutral-700">
              {{ 'profile.timezone_current' | translate }}:
              <span class="font-mono text-ink">{{ form.controls.timezone.value || '—' }}</span>
              @if (offsetLabel(form.controls.timezone.value); as off) {
                <span class="ml-1 font-mono text-neutral-700">({{ off }})</span>
              }
            </p>

            <label class="sr-only" for="tz_search">{{ 'profile.timezone_search' | translate }}</label>
            <input
              id="tz_search"
              type="search"
              autocomplete="off"
              [placeholder]="'profile.timezone_search' | translate"
              (input)="filterTimezones($any($event.target).value)"
              class="mb-2 w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink placeholder:text-neutral-500 focus:border-accent focus:outline-none"
            />
            <select
              #tzSelect
              id="timezone"
              formControlName="timezone"
              class="w-full rounded-none border border-divider bg-surface px-3 py-2 font-mono text-sm text-ink focus:border-accent focus:outline-none"
              size="8"
            >
              @for (tz of filteredTimezones(); track tz) {
                <option [value]="tz">{{ tz }}</option>
              }
            </select>
            @if (filteredTimezones().length === 0) {
              <p class="mt-1 text-[11px] text-down-deep" role="status">{{ 'profile.timezone_no_match' | translate }}</p>
            }
            <div class="mt-1.5 flex items-center justify-between gap-3">
              <p class="text-[11px] text-neutral-700">
                {{ 'profile.timezone_count' | translate: { shown: filteredTimezones().length, total: allTimezones().length } }}
              </p>
              <button type="button" (click)="useDetectedTimezone()"
                      class="rounded-none px-1 text-[11px] text-accent-700 underline hover:bg-accent-100">
                {{ 'profile.timezone_detect' | translate }} ({{ detectedTimezone }})
              </button>
            </div>
          </div>

          <div>
            <label class="mb-1 block text-xs font-medium text-neutral-700" for="language">
              {{ 'profile.language' | translate }}
            </label>
            <select id="language" formControlName="language"
                    class="w-full rounded-none border border-divider bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none">
              <option value="en">English</option>
            </select>
            <p class="mt-1 text-[11px] text-neutral-700">{{ 'profile.language_hint' | translate }}</p>
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

  @ViewChild('tzSelect') private tzSelect?: ElementRef<HTMLSelectElement>;

  saved = signal(false);
  allTimezones = signal<string[]>([]);
  filteredTimezones = signal<string[]>([]);

  /** The browser's own zone — offered as a one-click shortcut. */
  readonly detectedTimezone = ProfileComponent.detectTimezone();

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
    const tzs = fn ? fn('timeZone') : FALLBACK_TIMEZONES;
    this.allTimezones.set(tzs);
    this.filteredTimezones.set(tzs);

    await this.profile.load();
    const p = this.profile.profile();
    const u = this.auth.user();
    const timezone = p?.timezone ?? 'America/New_York';
    this.form.patchValue({
      display_name: u?.display_name ?? '',
      timezone,
      language: p?.language ?? 'en',
      notification_email: p?.notification_email ?? true,
    });
    // The saved zone must exist as an <option> or the select renders with
    // selectedIndex = -1 and shows nothing selected. That was the bug: the list
    // was sliced to the first 100 IANA names (Africa/* … America/A*), so any
    // user outside that alphabetical window — e.g. Asia/Jerusalem — opened
    // Settings to a listbox with no selection and no way to find their zone
    // except by guessing that the unlabelled search box above it was the answer.
    this._ensureSelectable(timezone);
    this._revealSelected();
  }

  /** Union the given zone into the option list so it is always selectable —
   *  covers both the initial load and a filter that would hide the current
   *  value. Also protects against a stored zone the browser doesn't enumerate. */
  private _ensureSelectable(tz: string): void {
    if (!tz) { return; }
    if (!this.allTimezones().includes(tz)) {
      this.allTimezones.set([tz, ...this.allTimezones()]);
    }
    if (!this.filteredTimezones().includes(tz)) {
      this.filteredTimezones.set([tz, ...this.filteredTimezones()]);
    }
  }

  /** Scroll the selected <option> into the 8-row viewport. Deferred a tick so
   *  the freshly-rendered options exist and the CVA has applied the value. */
  private _revealSelected(): void {
    setTimeout(() => {
      const el = this.tzSelect?.nativeElement;
      if (!el) { return; }
      const idx = Array.from(el.options).findIndex(o => o.value === this.form.controls.timezone.value);
      if (idx < 0) { return; }
      el.selectedIndex = idx;
      el.options[idx].scrollIntoView({ block: 'nearest' });
    });
  }

  filterTimezones(query: string): void {
    const q = query.toLowerCase().trim();
    // No slicing. ~420 IANA zones render fine, and truncating the list is what
    // made most zones unreachable by scrolling in the first place.
    this.filteredTimezones.set(
      q ? this.allTimezones().filter(tz => tz.toLowerCase().includes(q)) : this.allTimezones(),
    );
    this._ensureSelectable(this.form.controls.timezone.value);
    this._revealSelected();
  }

  /** Set the field to the browser-detected zone (one click instead of a search). */
  useDetectedTimezone(): void {
    this._ensureSelectable(this.detectedTimezone);
    this.form.controls.timezone.setValue(this.detectedTimezone);
    this.form.controls.timezone.markAsDirty();
    this._revealSelected();
  }

  /** `UTC+03:00`-style offset for a zone, or '' when it can't be resolved. */
  offsetLabel(tz: string): string {
    if (!tz) { return ''; }
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: tz, timeZoneName: 'longOffset',
      }).formatToParts(new Date());
      return parts.find(p => p.type === 'timeZoneName')?.value ?? '';
    } catch {
      return '';
    }
  }

  private static detectTimezone(): string {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
      return 'UTC';
    }
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
