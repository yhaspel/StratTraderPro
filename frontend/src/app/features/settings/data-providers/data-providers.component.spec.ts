import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { DataProvidersComponent } from './data-providers.component';
import { DataProvidersFacade } from '../../../abstraction/facades/data-providers.facade';
import { AuthStore } from '../../../abstraction/stores/auth.store';
import { DataProviderKeys } from '../../../core/models/data-providers.models';

describe('DataProvidersComponent — instance FMP/FRED keys (ADR-062)', () => {
  let facade: {
    keys: ReturnType<typeof signal>;
    loading: ReturnType<typeof signal>;
    error: ReturnType<typeof signal>;
    load: jasmine.Spy;
    set: jasmine.Spy;
    remove: jasmine.Spy;
  };

  const unconfigured: DataProviderKeys = {
    fmp: { provider: 'FMP', configured: false, source: null },
    fred: { provider: 'FRED', configured: false, source: null },
  };

  const envConfigured: DataProviderKeys = {
    fmp: { provider: 'FMP', configured: true, source: 'env' },
    fred: { provider: 'FRED', configured: false, source: null },
  };

  const uiConfigured: DataProviderKeys = {
    fmp: { provider: 'FMP', configured: true, source: 'ui', hint: 'abcd', updated_by: 'a@b.c' },
    fred: { provider: 'FRED', configured: false, source: null },
  };

  function setup(isStaff: boolean, keys: DataProviderKeys = unconfigured) {
    facade = {
      keys: signal(keys),
      loading: signal(false),
      error: signal(null),
      load: jasmine.createSpy('load'),
      set: jasmine.createSpy('set').and.resolveTo({ ok: true, value: uiConfigured }),
      remove: jasmine.createSpy('remove').and.resolveTo({ ok: true, value: unconfigured }),
    };
    TestBed.configureTestingModule({
      imports: [DataProvidersComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: DataProvidersFacade, useValue: facade },
        { provide: AuthStore, useValue: { user: signal({ email: 'a@b.c', is_staff: isStaff }) } },
      ],
    });
    const fixture = TestBed.createComponent(DataProvidersComponent);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('non-staff sees status but no key form and the staff-only note', () => {
    const el = setup(false).nativeElement as HTMLElement;
    expect(el.querySelectorAll('input').length).toBe(0);
    expect(el.textContent).toContain('data_providers.staff_only');
    expect(el.textContent).toContain('data_providers.status.not_configured');
  });

  it('staff sees one key input per provider', () => {
    const el = setup(true).nativeElement as HTMLElement;
    const inputs = Array.from(el.querySelectorAll('input[type="password"]'));
    expect(inputs.length).toBe(2);
    expect(facade.load).toHaveBeenCalled();
  });

  it('an env-var key renders as configured with the env label + precedence note', () => {
    const el = setup(true, envConfigured).nativeElement as HTMLElement;
    expect(el.textContent).toContain('data_providers.status.configured_env');
    expect(el.textContent).toContain('data_providers.env_active_note');
  });

  it('a UI-stored key shows the last-4 hint and who set it', () => {
    const el = setup(true, uiConfigured).nativeElement as HTMLElement;
    expect(el.textContent).toContain('…abcd');
    expect(el.textContent).toContain('a@b.c');
    expect(el.textContent).toContain('data_providers.status.configured_ui');
  });

  it('save sends the key through the facade once and wipes the input', async () => {
    const fixture = setup(true);
    const c = fixture.componentInstance;
    c.form('FMP').setValue({ api_key: 'fmp-key-123' });
    await c.onSave('FMP');
    expect(facade.set).toHaveBeenCalledOnceWith('FMP', 'fmp-key-123');
    expect(c.form('FMP').getRawValue().api_key).toBe('');
    expect(c.successes()['FMP']).toBe('saved');
  });

  it('a rejected key surfaces the dedicated INVALID_API_KEY message', async () => {
    const fixture = setup(true);
    const c = fixture.componentInstance;
    facade.set.and.resolveTo({ ok: false, error: { code: 'INVALID_API_KEY', message: 'no' } });
    c.form('FMP').setValue({ api_key: 'bad' });
    await c.onSave('FMP');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain(
      'data_providers.error.INVALID_API_KEY',
    );
  });

  it('remove requires the inline confirm and does not fire on first click', async () => {
    const fixture = setup(true, uiConfigured);
    const c = fixture.componentInstance;
    c.startRemove('FMP');
    expect(facade.remove).not.toHaveBeenCalled();
    await c.confirmRemove('FMP');
    expect(facade.remove).toHaveBeenCalledOnceWith('FMP');
    expect(c.successes()['FMP']).toBe('removed');
  });
});
