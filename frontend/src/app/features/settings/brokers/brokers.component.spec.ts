import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { BrokersComponent } from './brokers.component';
import { BrokersFacade } from '../../../abstraction/facades/brokers.facade';
import { AuthStore } from '../../../abstraction/stores/auth.store';

describe('BrokersComponent — flatten confirmation (P0-4)', () => {
  let facade: {
    accounts: ReturnType<typeof signal>;
    loading: ReturnType<typeof signal>;
    load: jasmine.Spy;
    flatten: jasmine.Spy;
  };

  const account = {
    id: 'acc-1',
    broker: 'ALPACA',
    mode: 'PAPER',
    is_default: true,
    account_number: 'PA1',
    nickname: '',
    status: 'CONNECTED',
    stream_status: 'CONNECTED',
    last_connected_at: null,
  };

  function setup(isStaff: boolean) {
    facade = {
      accounts: signal([account]),
      loading: signal(false),
      load: jasmine.createSpy('load'),
      flatten: jasmine.createSpy('flatten').and.resolveTo({ ok: true, value: { flattened: 1 } }),
    };
    TestBed.configureTestingModule({
      imports: [BrokersComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: BrokersFacade, useValue: facade },
        { provide: AuthStore, useValue: { user: signal({ email: 'a@b.c', is_staff: isStaff }) } },
      ],
    });
    const fixture = TestBed.createComponent(BrokersComponent);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => TestBed.resetTestingModule());

  function flattenButton(el: HTMLElement): HTMLButtonElement | undefined {
    return Array.from(el.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'brokers.connected.flatten',
    ) as HTMLButtonElement | undefined;
  }

  it('does not render the Flatten button for non-staff', () => {
    const el = setup(false).nativeElement as HTMLElement;
    expect(flattenButton(el)).toBeUndefined();
  });

  it('clicking Flatten opens the modal and does NOT call facade.flatten', () => {
    const fixture = setup(true);
    const el = fixture.nativeElement as HTMLElement;
    flattenButton(el)!.click();
    fixture.detectChanges();
    expect(fixture.componentInstance.flatteningId()).toBe('acc-1');
    expect(el.querySelector('[role="dialog"]')).toBeTruthy();
    expect(facade.flatten).not.toHaveBeenCalled();
  });

  it('cancel calls nothing', () => {
    const fixture = setup(true);
    fixture.componentInstance.onFlatten('acc-1');
    fixture.componentInstance.cancelFlatten();
    expect(facade.flatten).not.toHaveBeenCalled();
    expect(fixture.componentInstance.flatteningId()).toBeNull();
  });

  it('confirm requires the typed word, then calls facade.flatten exactly once', async () => {
    const fixture = setup(true);
    const c = fixture.componentInstance;
    c.onFlatten('acc-1');
    // Wrong / empty confirmation does nothing.
    await c.confirmFlatten();
    expect(facade.flatten).not.toHaveBeenCalled();
    // Correct typed confirmation fires once.
    c.flattenConfirm.set('FLATTEN');
    await c.confirmFlatten();
    expect(facade.flatten).toHaveBeenCalledOnceWith('acc-1');
    expect(c.flatteningId()).toBeNull();
  });
});
