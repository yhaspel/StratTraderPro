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

function buildFacade(overrides: Partial<AuthFacade> = {}): Partial<AuthFacade> {
  return {
    login: jasmine.createSpy('login').and.returnValue(Promise.resolve(true)),
    status: () => 'idle' as any,
    error: () => null,
    ...overrides,
  };
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
    const facade = buildFacade({ status: () => 'loading' as any });
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
});
