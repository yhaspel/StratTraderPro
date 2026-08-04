import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { ProfileComponent } from './profile.component';
import { ProfileFacade } from '../../../abstraction/facades/profile.facade';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

/**
 * Regression cover for the timezone field.
 *
 * The bug: the option list was `allTimezones.slice(0, 100)` — the first hundred
 * IANA names alphabetically, i.e. Africa/* through America/A*. A profile saved
 * as Asia/Jerusalem therefore had no matching <option>, so the <select> rendered
 * with selectedIndex = -1: nothing looked selected, the saved value was named
 * nowhere on screen, and scrolling the 6-row listbox could never reach the zone
 * the user wanted. It read as "timezone cannot be selected".
 */
describe('ProfileComponent — timezone field', () => {
  function setup(timezone: string) {
    const profileSignal = signal<{
      timezone: string; language: string; notification_email: boolean;
      default_broker_id: string | null; terms_version_accepted: string | null;
    } | null>({
      timezone, language: 'en', notification_email: true,
      default_broker_id: null, terms_version_accepted: null,
    });
    const update = jasmine.createSpy('update').and.resolveTo(true);
    TestBed.configureTestingModule({
      imports: [ProfileComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ProfileFacade,
          useValue: {
            load: jasmine.createSpy('load').and.resolveTo(),
            update,
            profile: profileSignal,
            loading: signal(false),
            error: signal(null),
          },
        },
        {
          provide: AuthFacade,
          useValue: { user: signal({ id: '1', email: 'a@b.c', display_name: 'A', is_verified: true }) },
        },
      ],
    });
    const fixture = TestBed.createComponent(ProfileComponent);
    return { fixture, update };
  }

  afterEach(() => TestBed.resetTestingModule());

  async function init(timezone: string) {
    const ctx = setup(timezone);
    ctx.fixture.detectChanges();
    await ctx.fixture.componentInstance.ngOnInit();
    ctx.fixture.detectChanges();
    return ctx;
  }

  it('renders every timezone, not a truncated window', async () => {
    const { fixture } = await init('Asia/Jerusalem');
    const c = fixture.componentInstance;
    expect(c.filteredTimezones().length).toBe(c.allTimezones().length);
    // The old cap was 100. Any real Intl list is far longer than that.
    expect(c.filteredTimezones().length).toBeGreaterThan(100);
  });

  it('renders the saved timezone as a selectable option', async () => {
    const { fixture } = await init('Asia/Jerusalem');
    const el = fixture.nativeElement as HTMLElement;
    const values = Array.from(el.querySelectorAll<HTMLOptionElement>('#timezone option')).map(o => o.value);
    expect(values).toContain('Asia/Jerusalem');
  });

  it('names the saved timezone in the form so it is visible without scrolling', async () => {
    const { fixture } = await init('Asia/Jerusalem');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Asia/Jerusalem');
  });

  it('keeps a stored zone the browser does not enumerate selectable', async () => {
    const { fixture } = await init('Not/AZone');
    const c = fixture.componentInstance;
    expect(c.filteredTimezones()).toContain('Not/AZone');
    expect(c.form.controls.timezone.value).toBe('Not/AZone');
  });

  it('filters on a substring and keeps the current value reachable', async () => {
    const { fixture } = await init('Asia/Jerusalem');
    const c = fixture.componentInstance;
    c.filterTimezones('london');
    fixture.detectChanges();
    expect(c.filteredTimezones().some(tz => tz.toLowerCase().includes('london'))).toBeTrue();
    // Filtering must not strand the saved value outside the option list.
    expect(c.filteredTimezones()).toContain('Asia/Jerusalem');
  });

  it('restores the whole list when the filter is cleared', async () => {
    const { fixture } = await init('Asia/Jerusalem');
    const c = fixture.componentInstance;
    const total = c.allTimezones().length;
    c.filterTimezones('london');
    c.filterTimezones('');
    expect(c.filteredTimezones().length).toBe(total);
  });

  it('applies the browser timezone on request', async () => {
    const { fixture } = await init('Asia/Jerusalem');
    const c = fixture.componentInstance;
    c.useDetectedTimezone();
    expect(c.form.controls.timezone.value).toBe(c.detectedTimezone);
    expect(c.filteredTimezones()).toContain(c.detectedTimezone);
  });

  it('submits the selected timezone', async () => {
    const { fixture, update } = await init('Asia/Jerusalem');
    const c = fixture.componentInstance;
    c.form.controls.timezone.setValue('Europe/London');
    await c.onSubmit();
    expect(update).toHaveBeenCalled();
    expect(update.calls.mostRecent().args[0].timezone).toBe('Europe/London');
  });

  it('renders a UTC offset for a known zone and degrades to empty for junk', async () => {
    const { fixture } = await init('Asia/Jerusalem');
    const c = fixture.componentInstance;
    expect(c.offsetLabel('UTC').length).toBeGreaterThan(0);
    expect(c.offsetLabel('Not/AZone')).toBe('');
    expect(c.offsetLabel('')).toBe('');
  });
});
