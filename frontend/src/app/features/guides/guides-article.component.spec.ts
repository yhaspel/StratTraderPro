import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';
import { of } from 'rxjs';
import { GuidesArticleComponent } from './guides-article.component';
import { GUIDE_ARTICLES, GUIDE_SECTIONS, GUIDE_SLUGS } from './guides.catalog';

describe('GuidesArticleComponent', () => {
  function setup(slug: string) {
    TestBed.configureTestingModule({
      imports: [GuidesArticleComponent, TranslateModule.forRoot()],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { paramMap: of(convertToParamMap({ slug })) } },
      ],
    });
    const fixture = TestBed.createComponent(GuidesArticleComponent);
    fixture.detectChanges();
    return { fixture, http: TestBed.inject(HttpTestingController) };
  }

  afterEach(() => TestBed.resetTestingModule());

  it('loads and renders a valid slug (sanitized)', () => {
    const { fixture, http } = setup('mfa');
    http.expectOne('assets/guides/mfa.html').flush('<h1>Two-factor</h1><p>Hi</p>');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).innerHTML).toContain('Two-factor');
    http.verify();
  });

  it('strips injected script / onerror from guide HTML (P2-12)', () => {
    const { fixture, http } = setup('mfa');
    http.expectOne('assets/guides/mfa.html').flush(
      '<h1>Ok</h1><script>window.__pwned=1</script><img src="x" onerror="window.__pwned=1">',
    );
    fixture.detectChanges();
    const html = (fixture.nativeElement as HTMLElement).innerHTML;
    expect(html).toContain('Ok');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('onerror');
  });

  it('keeps <img src> in guide HTML (step screenshots must survive sanitizing)', () => {
    const { fixture, http } = setup('mfa');
    http.expectOne('assets/guides/mfa.html').flush(
      '<figure><img src="assets/guides/img/step.png" alt="Step 1"><figcaption>Step 1</figcaption></figure>',
    );
    fixture.detectChanges();
    const img = (fixture.nativeElement as HTMLElement).querySelector('img');
    expect(img).not.toBeNull();
    expect(img!.getAttribute('src')).toContain('assets/guides/img/step.png');
  });

  it('shows not-found for a slug that is not in the catalog, without any HTTP call', () => {
    const { fixture, http } = setup('does-not-exist');
    http.verify(); // catalog allow-list blocks it — no request is issued
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('help.not_found.title');
  });

  it('rejects a path-traversal slug without any HTTP call', () => {
    const { fixture, http } = setup('../secret');
    http.verify();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('help.not_found');
  });

  it('exposes prev/next inside the flat catalog order', () => {
    const second = GUIDE_ARTICLES[1].slug;
    const { fixture, http } = setup(second);
    http.expectOne('assets/guides/' + second + '.html').flush('<h1>x</h1>');
    fixture.detectChanges();
    expect(fixture.componentInstance.prev()?.slug).toBe(GUIDE_ARTICLES[0].slug);
    expect(fixture.componentInstance.next()?.slug).toBe(GUIDE_ARTICLES[2].slug);
    http.verify();
  });
});

describe('guides catalog', () => {
  it('has no duplicate slugs', () => {
    expect(GUIDE_SLUGS.size).toBe(GUIDE_ARTICLES.length);
  });

  it('gives every article a title and a summary', () => {
    for (const a of GUIDE_ARTICLES) {
      expect(a.title.length).toBeGreaterThan(0);
      expect(a.summary.length).toBeGreaterThan(0);
    }
  });

  it('uses slugs that cannot escape assets/guides/', () => {
    for (const a of GUIDE_ARTICLES) {
      expect(a.slug).toMatch(/^[a-z0-9-]+$/);
    }
  });

  it('has no empty sections', () => {
    for (const s of GUIDE_SECTIONS) {
      expect(s.articles.length).toBeGreaterThan(0);
    }
  });
});
