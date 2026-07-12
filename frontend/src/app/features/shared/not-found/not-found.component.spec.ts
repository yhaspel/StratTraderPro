import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { NotFoundComponent } from './not-found.component';
import { AuthStore } from '../../../abstraction/stores/auth.store';

describe('NotFoundComponent', () => {
  function setup(authed: boolean) {
    TestBed.configureTestingModule({
      imports: [NotFoundComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        { provide: AuthStore, useValue: { isAuthenticated: () => authed } },
      ],
    });
    const fixture = TestBed.createComponent(NotFoundComponent);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('links home to the landing when anonymous', () => {
    const href = setup(false).nativeElement.querySelector('a').getAttribute('href');
    expect(href).toBe('/');
  });

  it('links home to the dashboard when authenticated', () => {
    const href = setup(true).nativeElement.querySelector('a').getAttribute('href');
    expect(href).toBe('/dashboard');
  });
});
