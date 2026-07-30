import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { AdminHealthComponent } from './admin-health.component';
import { AdminFacade } from '../../abstraction/facades/admin.facade';
import { ConfigService } from '../../core/services/config.service';
import { AdminHealth } from '../../core/models/admin.models';

/**
 * Regression cover for the health cards.
 *
 * `sentiment_backlog` has always been `{depth, oldest_age_min, alert}` on the
 * wire; the SPA typed it `number` and interpolated the object, so the card read
 * `[object Object]`. `active_halts` ({total, platform}) and `flags_overridden`
 * (a count) had the same drift, typed as string arrays — `.length === 0` on an
 * object is `undefined === 0`, i.e. false, so those two cards rendered *nothing*:
 * no value and no empty state.
 */
describe('AdminHealthComponent', () => {
  const BASE: AdminHealth = {
    queue_depths: { celery: 0 },
    broker_streams: { CONNECTED: 1 },
    hmm_model_age_seconds: null,
    sentiment_backlog: { depth: 12, oldest_age_min: 3.4, alert: false },
    db_ok: true,
    redis_ok: true,
    verifier: { last_verified_id: 80, run_at: null, result: 'ok' },
    active_halts: { total: 0, platform: false },
    flags_overridden: 0,
    regime_source_configured: true,
    generated_at: '2026-07-29T18:25:45Z',
  };

  function setup(health: Partial<AdminHealth> = {}) {
    TestBed.configureTestingModule({
      imports: [AdminHealthComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: AdminFacade,
          useValue: {
            loadHealth: jasmine.createSpy('loadHealth').and.resolveTo(),
            health: signal<AdminHealth>({ ...BASE, ...health }),
            loading: signal(false),
            error: signal(null),
            // Consumed by the nested <app-impersonation-banner>.
            impersonation: signal(null),
            selectedUser: signal(null),
            stopImpersonation: jasmine.createSpy('stopImpersonation').and.resolveTo({ ok: true }),
          },
        },
        { provide: ConfigService, useValue: { grafanaUrl: '' } },
      ],
    });
    const fixture = TestBed.createComponent(AdminHealthComponent);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => TestBed.resetTestingModule());

  function text(fixture: { nativeElement: unknown }): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  it('never renders the literal [object Object]', () => {
    expect(text(setup())).not.toContain('[object Object]');
  });

  it('renders the backlog depth, not the backlog object', () => {
    expect(text(setup())).toContain('12');
  });

  it('falls back to an em dash when the backlog section degraded to {}', () => {
    const fixture = setup({ sentiment_backlog: {} });
    expect(text(fixture)).toContain('—');
    expect(text(fixture)).not.toContain('[object Object]');
  });

  it('survives a backlog field the backend omitted entirely', () => {
    const fixture = setup({ sentiment_backlog: undefined });
    expect(text(fixture)).not.toContain('[object Object]');
  });

  it('flags an alerting backlog', () => {
    const fixture = setup({ sentiment_backlog: { depth: 900, oldest_age_min: 61, alert: true } });
    expect(text(fixture)).toContain('admin.health.sentiment_alert');
  });

  it('shows the no-halts empty state when active_halts.total is 0', () => {
    expect(text(setup())).toContain('admin.health.no_halts');
  });

  it('shows the halt count and a platform chip when halts are active', () => {
    const fixture = setup({ active_halts: { total: 3, platform: true } });
    expect(text(fixture)).toContain('3');
    expect(text(fixture)).toContain('admin.health.halt_platform');
    expect(text(fixture)).not.toContain('admin.health.no_halts');
  });

  it('shows the no-overrides empty state when flags_overridden is 0', () => {
    expect(text(setup())).toContain('admin.health.no_overrides');
  });

  it('renders flags_overridden as a count when non-zero', () => {
    const fixture = setup({ flags_overridden: 4 });
    expect(text(fixture)).toContain('4');
    expect(text(fixture)).not.toContain('admin.health.no_overrides');
  });

  it('reports an unconfigured regime data source', () => {
    const fixture = setup({ regime_source_configured: false });
    expect(text(fixture)).toContain('admin.health.regime_source_missing');
    expect(text(fixture)).toContain('admin.health.regime_source_hint');
  });

  it('hides the regime-source card on a backend that does not send the field', () => {
    const fixture = setup({ regime_source_configured: undefined });
    expect(text(fixture)).not.toContain('admin.health.regime_source_missing');
    expect(text(fixture)).not.toContain('admin.health.regime_source_ok');
  });
});
