import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { StrategiesListComponent } from './strategies-list.component';
import { StrategiesFacade } from '../../../abstraction/facades/strategies.facade';

describe('StrategiesListComponent — enable confirmation (P1-10)', () => {
  let facade: {
    strategies: ReturnType<typeof signal>;
    loading: ReturnType<typeof signal>;
    error: ReturnType<typeof signal>;
    load: jasmine.Spy;
    toggleEnabled: jasmine.Spy;
    softDelete: jasmine.Spy;
    clearRevealedSecret: jasmine.Spy;
  };

  const strat = (over: Record<string, unknown> = {}) => ({
    id: 's1', name: 'S1', description_short: '', is_system: false,
    is_enabled: false, has_webhook_config: false, ...over,
  });

  function setup(strategies: unknown[]) {
    facade = {
      strategies: signal(strategies),
      loading: signal(false),
      error: signal(null),
      load: jasmine.createSpy('load'),
      toggleEnabled: jasmine.createSpy('toggleEnabled').and.resolveTo(),
      softDelete: jasmine.createSpy('softDelete').and.resolveTo(),
      clearRevealedSecret: jasmine.createSpy('clearRevealedSecret'),
    };
    TestBed.configureTestingModule({
      imports: [StrategiesListComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: StrategiesFacade, useValue: facade },
      ],
    });
    const fixture = TestBed.createComponent(StrategiesListComponent);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('enabling opens the modal and does NOT toggle until confirmed', () => {
    const fixture = setup([strat({ is_enabled: false })]);
    const c = fixture.componentInstance;
    c.onToggle(strat({ is_enabled: false }) as never);
    fixture.detectChanges();
    expect(c.enablingStrategy()).toBeTruthy();
    expect(facade.toggleEnabled).not.toHaveBeenCalled();
    expect((fixture.nativeElement as HTMLElement).querySelector('[role="dialog"]')).toBeTruthy();
  });

  it('confirm enables exactly once; cancel does nothing', async () => {
    const fixture = setup([strat()]);
    const c = fixture.componentInstance;
    c.onToggle(strat({ id: 's1', is_enabled: false }) as never);
    c.cancelEnable();
    expect(facade.toggleEnabled).not.toHaveBeenCalled();
    c.onToggle(strat({ id: 's1', is_enabled: false }) as never);
    await c.confirmEnable();
    expect(facade.toggleEnabled).toHaveBeenCalledOnceWith('s1', true);
  });

  it('disabling toggles immediately without a modal', () => {
    const fixture = setup([strat({ is_enabled: true })]);
    fixture.componentInstance.onToggle(strat({ id: 's1', is_enabled: true }) as never);
    expect(facade.toggleEnabled).toHaveBeenCalledOnceWith('s1', false);
    expect(fixture.componentInstance.enablingStrategy()).toBeNull();
  });

  it('the toggle exposes role=switch + aria-checked', () => {
    const el = setup([strat({ is_enabled: true })]).nativeElement as HTMLElement;
    const sw = el.querySelector('[role="switch"]');
    expect(sw).toBeTruthy();
    expect(sw!.getAttribute('aria-checked')).toBe('true');
  });
});
