import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { LandingComponent } from './landing.component';
import { ConfigService } from '../../core/services/config.service';

describe('LandingComponent', () => {
  let router: jasmine.SpyObj<Router>;

  function setup(env = 'production') {
    router = jasmine.createSpyObj('Router', ['navigate']);
    TestBed.configureTestingModule({
      imports: [LandingComponent, TranslateModule.forRoot()],
      providers: [
        { provide: Router, useValue: router },
        { provide: ConfigService, useValue: { sentryEnvironment: env } },
      ],
    });
    const fixture = TestBed.createComponent(LandingComponent);
    const translate = TestBed.inject(TranslateService);
    translate.setTranslation('en', {
      app: { title: 'StratTraderPro' },
      landing: {
        hero: {
          tag: 'SELF-HOSTED · YOU OWN THE KEYS',
          title_pre: 'Webhook-driven algo trading, on',
          title_em: 'your',
          title_post: 'infrastructure.',
          subtitle: 'Sub',
        },
        cta: { sign_in: 'Sign in', create_account: 'Create account' },
        how: { title: 'How it works' },
        steps: {},
        disclaimer: 'Paper only',
      },
    });
    translate.use('en');
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('renders the brand wordmark and the hero headline', () => {
    const el = setup().nativeElement as HTMLElement;
    expect(el.querySelector('header')?.textContent).toContain('StratTraderPro');
    expect(el.querySelector('h1')?.textContent).toContain('your');
    expect(el.querySelector('h1')?.textContent).toContain('infrastructure.');
  });

  it('navigates to /login and /register from the header and hero CTAs', () => {
    const el = setup().nativeElement as HTMLElement;
    const buttons = el.querySelectorAll('app-button button');
    expect(buttons.length).toBe(3);
    (buttons[0] as HTMLButtonElement).click(); // header "Sign in"
    (buttons[1] as HTMLButtonElement).click(); // hero "Sign in" (blueprint-framed primary)
    (buttons[2] as HTMLButtonElement).click(); // hero "Create account"
    expect(router.navigate).toHaveBeenCalledTimes(3);
    expect(router.navigate.calls.argsFor(0)).toEqual([['/login']]);
    expect(router.navigate.calls.argsFor(1)).toEqual([['/login']]);
    expect(router.navigate.calls.argsFor(2)).toEqual([['/register']]);
  });

  it('hides the environment badge in production', () => {
    const el = setup('production').nativeElement as HTMLElement;
    expect(el.textContent).not.toContain('production');
  });

  it('shows the environment badge outside production', () => {
    const el = setup('staging').nativeElement as HTMLElement;
    expect(el.textContent).toContain('staging');
  });
});
