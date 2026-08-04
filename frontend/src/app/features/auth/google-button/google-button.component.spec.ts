import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { TranslateModule } from '@ngx-translate/core';
import { GoogleButtonComponent } from './google-button.component';
import { AuthFacade } from '../../../abstraction/facades/auth.facade';

describe('GoogleButtonComponent', () => {
  function create(available: boolean | null) {
    const load = jasmine.createSpy('loadGoogleAvailability').and.returnValue(Promise.resolve());
    const facade = {
      googleAvailable: signal(available),
      loadGoogleAvailability: load,
      status: (() => 'idle') as unknown,
      startGoogleSignIn: jasmine.createSpy('startGoogleSignIn').and.returnValue(Promise.resolve()),
    } as unknown as AuthFacade;
    TestBed.configureTestingModule({
      imports: [GoogleButtonComponent, TranslateModule.forRoot()],
      providers: [{ provide: AuthFacade, useValue: facade }],
    });
    const fixture = TestBed.createComponent(GoogleButtonComponent);
    fixture.detectChanges();
    return { fixture, load };
  }

  afterEach(() => TestBed.resetTestingModule());

  it('probes availability on init', () => {
    const { load } = create(null);
    expect(load).toHaveBeenCalled();
  });

  it('renders nothing while availability is unknown', () => {
    const { fixture } = create(null);
    expect(fixture.nativeElement.querySelector('button')).toBeNull();
  });

  it('renders nothing when Google is unavailable', () => {
    const { fixture } = create(false);
    expect(fixture.nativeElement.querySelector('button')).toBeNull();
  });

  it('renders the button when Google is available', () => {
    const { fixture } = create(true);
    expect(fixture.nativeElement.querySelector('button')).toBeTruthy();
  });
});
