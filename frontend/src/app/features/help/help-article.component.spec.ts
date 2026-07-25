import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { of } from 'rxjs';
import { HelpArticleComponent } from './help-article.component';

describe('HelpArticleComponent', () => {
  function setup(slug: string) {
    TestBed.configureTestingModule({
      imports: [HelpArticleComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ slug })) } },
      ],
    });
    const fixture = TestBed.createComponent(HelpArticleComponent);
    fixture.detectChanges();
    return { fixture, http: TestBed.inject(HttpTestingController) };
  }

  afterEach(() => TestBed.resetTestingModule());

  it('loads and renders a valid slug (sanitized)', () => {
    const { fixture, http } = setup('mfa');
    http.expectOne('assets/help/mfa.html').flush('<h1>Two-factor</h1><p>Hi</p>');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).innerHTML).toContain('Two-factor');
    http.verify();
  });

  it('strips injected script / onerror from help HTML (P2-12)', () => {
    const { fixture, http } = setup('mfa');
    http.expectOne('assets/help/mfa.html').flush(
      '<h1>Ok</h1><script>window.__pwned=1</script><img src="x" onerror="window.__pwned=1">',
    );
    fixture.detectChanges();
    const html = (fixture.nativeElement as HTMLElement).innerHTML;
    expect(html).toContain('Ok');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('onerror');
  });

  it('shows not-found for an unknown slug (404)', () => {
    const { fixture, http } = setup('does-not-exist');
    http.expectOne('assets/help/does-not-exist.html').flush('nope', { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('help.not_found.title');
    http.verify();
  });

  it('rejects a path-traversal slug without any HTTP call', () => {
    const { fixture, http } = setup('../secret');
    http.verify(); // SLUG_RE blocks it — no request is issued
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('help.not_found');
  });
});
