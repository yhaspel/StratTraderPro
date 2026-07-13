/**
 * AuthFacade — Google-availability probe.
 *
 * Regression cover for the "Continue with Google is missing" bug: the probe used
 * to cache `false` on ANY error, so a 502 while the backend redeployed made the
 * button vanish for the rest of the session even though Google was configured
 * and enabled the whole time. A transport failure is not an answer.
 */
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { AuthFacade } from './auth.facade';
import { AuthApi } from '../../core/services/auth.api';
import { AuthStore } from '../stores/auth.store';
import { DashboardWsService } from '../../core/services/ws.service';

describe('AuthFacade — Google availability probe', () => {
  let facade: AuthFacade;
  let api: jasmine.SpyObj<AuthApi>;

  beforeEach(() => {
    api = jasmine.createSpyObj('AuthApi', ['oauthGoogleAvailable']);

    TestBed.configureTestingModule({
      providers: [
        AuthFacade,
        AuthStore,
        { provide: AuthApi, useValue: api },
        { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
        {
          provide: DashboardWsService,
          useValue: jasmine.createSpyObj('DashboardWsService', ['forceDisconnect']),
        },
      ],
    });
    facade = TestBed.inject(AuthFacade);
  });

  it('shows the button when the backend says enabled', async () => {
    api.oauthGoogleAvailable.and.returnValue(of({ data: { enabled: true } }));

    await facade.loadGoogleAvailability();

    expect(facade.googleAvailable()).toBe(true);
  });

  it('hides the button when the backend says disabled', async () => {
    api.oauthGoogleAvailable.and.returnValue(of({ data: { enabled: false } }));

    await facade.loadGoogleAvailability();

    expect(facade.googleAvailable()).toBe(false);
  });

  it('hides the button on a 4xx — the backend answered, and the answer is no', async () => {
    api.oauthGoogleAvailable.and.returnValue(throwError(() => ({ status: 404 })));

    await facade.loadGoogleAvailability();

    expect(facade.googleAvailable()).toBe(false);
  });

  it('retries a 502 and succeeds when the backend comes back', async () => {
    let call = 0;
    api.oauthGoogleAvailable.and.callFake(() => {
      call += 1;
      return call === 1
        ? throwError(() => ({ status: 502 }))
        : of({ data: { enabled: true } });
    });

    await facade.loadGoogleAvailability();

    expect(call).toBe(2);
    expect(facade.googleAvailable()).toBe(true);
  });

  it('stays UNKNOWN (not false) when the backend never answers, so a later mount re-probes', async () => {
    api.oauthGoogleAvailable.and.returnValue(throwError(() => ({ status: 502 })));

    await facade.loadGoogleAvailability();

    // The bug: this used to be `false`, and `false` is sticky — the button was
    // gone until a full page reload. `null` means "ask again next time".
    expect(facade.googleAvailable()).toBeNull();

    // Backend is back; the next mount probes again and the button returns.
    api.oauthGoogleAvailable.and.returnValue(of({ data: { enabled: true } }));
    await facade.loadGoogleAvailability();
    expect(facade.googleAvailable()).toBe(true);
  });

  it('does not re-probe once it has a definitive answer', async () => {
    api.oauthGoogleAvailable.and.returnValue(of({ data: { enabled: true } }));

    await facade.loadGoogleAvailability();
    await facade.loadGoogleAvailability();

    expect(api.oauthGoogleAvailable).toHaveBeenCalledTimes(1);
  });

  it('shares one in-flight probe between concurrent callers (login + register)', async () => {
    api.oauthGoogleAvailable.and.returnValue(of({ data: { enabled: true } }));

    await Promise.all([
      facade.loadGoogleAvailability(),
      facade.loadGoogleAvailability(),
    ]);

    expect(api.oauthGoogleAvailable).toHaveBeenCalledTimes(1);
  });
});
