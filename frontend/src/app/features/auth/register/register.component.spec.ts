import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { RegisterComponent } from './register.component';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

function buildFacade(overrides: Record<string, unknown> = {}): Partial<AuthFacade> {
  return {
    register: jasmine.createSpy('register').and.returnValue(Promise.resolve(true)),
    resetFormState: jasmine.createSpy('resetFormState'),
    status: (() => 'idle') as unknown as AuthFacade['status'],
    error: (() => null) as unknown as AuthFacade['error'],
    googleAvailable: (() => false) as unknown as AuthFacade['googleAvailable'],
    loadGoogleAvailability: jasmine.createSpy('loadGoogleAvailability').and.returnValue(Promise.resolve()),
    ...overrides,
  } as Partial<AuthFacade>;
}

describe('RegisterComponent — validation', () => {
  function create(facade: Partial<AuthFacade> = buildFacade()) {
    TestBed.configureTestingModule({
      imports: [RegisterComponent, TranslateModule.forRoot()],
      providers: [provideRouter([]), { provide: AuthFacade, useValue: facade }],
    });
    const fixture = TestBed.createComponent(RegisterComponent);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('is invalid when empty', () => {
    expect(create().componentInstance.form.invalid).toBeTrue();
  });

  it('rejects a password under 12 characters', () => {
    const c = create().componentInstance;
    c.form.setValue({ email: 'u@e.com', displayName: 'U', password: 'short1' });
    expect(c.form.controls.password.errors?.['minlength']).toBeTruthy();
    expect(c.form.invalid).toBeTrue();
  });

  it('rejects a 12+ char password without a digit (matches the hint)', () => {
    const c = create().componentInstance;
    c.form.setValue({ email: 'u@e.com', displayName: 'U', password: 'abcdefghijkl' });
    expect(c.form.controls.password.errors?.['lettersAndDigits']).toBeTruthy();
    expect(c.form.invalid).toBeTrue();
  });

  it('is valid with a 12+ char letters+digits password', () => {
    const c = create().componentInstance;
    c.form.setValue({ email: 'u@e.com', displayName: 'U', password: 'SecurePass1234' });
    expect(c.form.valid).toBeTrue();
  });

  it('accepts a non-Latin (Unicode) letters+digits password, matching the backend', () => {
    // ASCII-only validation would wrongly reject this and re-create the bug
    // for non-Latin-script users (backend str.isalpha()/isdigit() accept it).
    const c = create().componentInstance;
    c.form.setValue({ email: 'u@e.com', displayName: 'U', password: 'пароль1234567' });
    expect(c.form.controls.password.errors?.['lettersAndDigits']).toBeFalsy();
    expect(c.form.valid).toBeTrue();
  });

  it('renders a field error once the control is touched', () => {
    const fixture = create();
    const c = fixture.componentInstance;
    c.form.controls.password.setValue('short1');
    c.form.controls.password.markAsTouched(); // real typing dirties; simulate here
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('p[role="alert"]')).toBeTruthy();
  });

  it('calls facade.register on a valid submit', async () => {
    const facade = buildFacade();
    const fixture = create(facade);
    fixture.componentInstance.form.setValue({ email: 'u@e.com', displayName: 'U', password: 'SecurePass1234' });
    await fixture.componentInstance.onSubmit();
    expect(facade.register as jasmine.Spy).toHaveBeenCalledWith('u@e.com', 'U', 'SecurePass1234');
  });

  it('does not call facade.register when invalid', async () => {
    const facade = buildFacade();
    const fixture = create(facade);
    await fixture.componentInstance.onSubmit();
    expect(facade.register as jasmine.Spy).not.toHaveBeenCalled();
  });
});
