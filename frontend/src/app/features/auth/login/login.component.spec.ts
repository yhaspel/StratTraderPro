import { TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { provideRouter } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { LoginComponent } from './login.component';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';
import {
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

function buildFacade(overrides: Record<string, unknown> = {}): Partial<AuthFacade> {
  // Cast through unknown — the test only exercises template branches that
  // call status() and error() like signals, but the structural Signal<T>
  // type carries an opaque brand we don't need to recreate for a mock.
  return {
    login: jasmine.createSpy('login').and.returnValue(Promise.resolve(true)),
    // Stubbed because LoginComponent's constructor calls it to clear any
    // stale 'loading' status carried over from the register screen.
    resetFormState: jasmine.createSpy('resetFormState'),
    status: (() => 'idle') as unknown as AuthFacade['status'],
    error: (() => null) as unknown as AuthFacade['error'],
    // The embedded <app-google-button> probes these on init.
    googleAvailable: (() => false) as unknown as AuthFacade['googleAvailable'],
    loadGoogleAvailability: jasmine.createSpy('loadGoogleAvailability').and.returnValue(Promise.resolve()),
    ...overrides,
  } as Partial<AuthFacade>;
}

describe('LoginComponent — form validators', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LoginComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([])),
        provideHttpClientTesting(),
        { provide: AuthFacade, useValue: buildFacade() },
      ],
    }).compileComponents();
  });

  it('form is invalid when empty', () => {
    const fixture = TestBed.createComponent(LoginComponent);
    expect(fixture.componentInstance.form.invalid).toBeTrue();
  });

  it('form is invalid with a non-email string', () => {
    const fixture = TestBed.createComponent(LoginComponent);
    fixture.componentInstance.form.setValue({ email: 'not-an-email', password: 'secret' });
    expect(fixture.componentInstance.form.get('email')!.invalid).toBeTrue();
  });

  it('form is valid with a proper email and any non-empty password', () => {
    const fixture = TestBed.createComponent(LoginComponent);
    fixture.componentInstance.form.setValue({ email: 'user@example.com', password: 'pass123' });
    expect(fixture.componentInstance.form.valid).toBeTrue();
  });

  it('submit button is disabled while loading', () => {
    const facade = buildFacade({ status: (() => 'loading') as unknown });
    TestBed.overrideProvider(AuthFacade, { useValue: facade });
    const fixture = TestBed.createComponent(LoginComponent);
    fixture.componentInstance.form.setValue({ email: 'u@e.com', password: 'pw' });
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type=submit]');
    expect(btn.disabled).toBeTrue();
  });

  it('calls facade.login with form values on submit', async () => {
    const facade = buildFacade();
    TestBed.overrideProvider(AuthFacade, { useValue: facade });
    const fixture = TestBed.createComponent(LoginComponent);
    fixture.componentInstance.form.setValue({ email: 'u@e.com', password: 'mypassword' });
    await fixture.componentInstance.onSubmit();
    expect(facade.login as jasmine.Spy).toHaveBeenCalledWith('u@e.com', 'mypassword');
  });

  it('does not call facade.login when form is invalid', async () => {
    const facade = buildFacade();
    TestBed.overrideProvider(AuthFacade, { useValue: facade });
    const fixture = TestBed.createComponent(LoginComponent);
    await fixture.componentInstance.onSubmit();
    expect(facade.login as jasmine.Spy).not.toHaveBeenCalled();
  });

  it('resets stale form state on init so the submit button is not stuck disabled', () => {
    // Repro of the "register → /resend-verification → back to /login" bug:
    // status='loading' from the prior register call carries over and would
    // otherwise keep the button disabled forever. The constructor must call
    // facade.resetFormState() to clear it.
    const facade = buildFacade({ status: (() => 'loading') as unknown });
    TestBed.overrideProvider(AuthFacade, { useValue: facade });
    TestBed.createComponent(LoginComponent);
    expect(facade.resetFormState as jasmine.Spy).toHaveBeenCalled();
  });
});
