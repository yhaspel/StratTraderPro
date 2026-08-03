import { renderTradingViewDescription as render } from './tradingview-description';

describe('renderTradingViewDescription', () => {
  it('returns empty string for empty/blank input', () => {
    expect(render('')).toBe('');
    expect(render(null as unknown as string)).toBe('');
  });

  it('escapes plain text and converts newlines to <br>', () => {
    expect(render('a & b < c > d')).toBe('a &amp; b &lt; c &gt; d');
    expect(render('line1\nline2')).toBe('line1<br>line2');
  });

  describe('inline formatting', () => {
    it('bold → <strong>', () => {
      expect(render('[b]hi[/b]')).toBe('<strong>hi</strong>');
    });
    it('italic → <em>', () => {
      expect(render('[i]hi[/i]')).toBe('<em>hi</em>');
    });
    it('strikethrough → <s>', () => {
      expect(render('[s]hi[/s]')).toBe('<s>hi</s>');
    });
    it('is case-insensitive on tag names', () => {
      expect(render('[B]hi[/B]')).toBe('<strong>hi</strong>');
    });
    it('nests inline tags', () => {
      expect(render('[b][i]x[/i][/b]')).toBe('<strong><em>x</em></strong>');
    });
    it('auto-closes an unclosed inline tag at end', () => {
      expect(render('[b]bold')).toBe('<strong>bold</strong>');
    });
    it('auto-closes overlapping inline tags', () => {
      expect(render('[b][i]x[/b]')).toBe('<strong><em>x</em></strong>');
    });
    it('drops a stray closing tag', () => {
      expect(render('x[/b]y')).toBe('xy');
    });
  });

  describe('links', () => {
    it('renders an https link with the label as text', () => {
      const out = render('[url=https://example.com]click[/url]');
      expect(out).toBe(
        '<a href="https://example.com" target="_blank" rel="nofollow noopener noreferrer">click</a>',
      );
    });
    it('allows site-relative URLs', () => {
      expect(render('[url=/strategies]x[/url]')).toContain('href="/strategies"');
    });
    it('escapes & inside the URL', () => {
      expect(render('[url=https://x.com?a=1&b=2]q[/url]')).toContain(
        'href="https://x.com?a=1&amp;b=2"',
      );
    });
    it('rejects javascript: URLs and shows the label as plain text', () => {
      const out = render('[url=javascript:alert(1)]click[/url]');
      expect(out).toBe('click');
      expect(out).not.toContain('javascript:');
      expect(out).not.toContain('<a');
    });
    it('rejects protocol-relative //host URLs', () => {
      expect(render('[url=//evil.com]x[/url]')).toBe('x');
    });
    it('rejects the backslash form /\\host (browsers resolve it cross-origin)', () => {
      const out = render('[url=/\\evil.com]x[/url]');
      expect(out).toBe('x');
      expect(out).not.toContain('<a');
    });
    it('shows a label-less [url] as plain text (unsupported form)', () => {
      expect(render('[url]https://x.com[/url]')).toBe('https://x.com');
    });
  });

  describe('lists', () => {
    it('bulleted list', () => {
      expect(render('[list][*]a[*]b[/list]')).toBe('<ul><li>a</li><li>b</li></ul>');
    });
    it('numbered list via [list=1]', () => {
      expect(render('[list=1][*]a[*]b[/list]')).toBe('<ol><li>a</li><li>b</li></ol>');
    });
    it('swallows newlines/whitespace between the list container and items', () => {
      expect(render('[list]\n[*]a\n[*]b\n[/list]')).toBe('<ul><li>a</li><li>b</li></ul>');
    });
    it('auto-closes an unclosed list at end', () => {
      expect(render('[list][*]a')).toBe('<ul><li>a</li></ul>');
    });
    it('allows inline formatting inside a list item', () => {
      expect(render('[list][*]a [b]bold[/b][/list]')).toBe(
        '<ul><li>a <strong>bold</strong></li></ul>',
      );
    });
    it('ignores a stray [*] outside any list', () => {
      expect(render('[*]orphan')).toBe('orphan');
    });
    it('closes an open inline tag before a block so nesting stays valid', () => {
      const out = render('[b][list][*]x[/list][/b]');
      expect(out).not.toContain('<strong><ul>'); // block never nested inside inline
      expect(out).toContain('<ul><li>x</li></ul>');
    });
  });

  describe('robustness', () => {
    it('handles a long blank-line run without catastrophic backtracking', () => {
      // Regression guard for the ReDoS in cleanupBlockBreaks: linear now, so this
      // returns instantly instead of freezing for seconds.
      const out = render('\n'.repeat(20000));
      expect(out).toBe('<br>'.repeat(20000));
    });
  });

  describe('quote', () => {
    it('renders a blockquote', () => {
      expect(render('[quote]wise words[/quote]')).toBe('<blockquote>wise words</blockquote>');
    });
    it('keeps multi-line breaks inside a quote', () => {
      expect(render('[quote]a\nb[/quote]')).toBe('<blockquote>a<br>b</blockquote>');
    });
  });

  describe('pine code block', () => {
    it('renders a <pre><code> block', () => {
      expect(render('[pine]plot(close)[/pine]')).toBe('<pre><code>plot(close)</code></pre>');
    });
    it('preserves literal square brackets (history operator)', () => {
      expect(render('[pine]x = close[1][/pine]')).toBe('<pre><code>x = close[1]</code></pre>');
    });
    it('preserves newlines literally inside the code block', () => {
      expect(render('[pine]a\nb[/pine]')).toBe('<pre><code>a\nb</code></pre>');
    });
    it('escapes html inside the code block', () => {
      expect(render('[pine]a < b[/pine]')).toBe('<pre><code>a &lt; b</code></pre>');
    });
    it('handles an unterminated [pine] by consuming the rest as code', () => {
      expect(render('[pine]tail')).toBe('<pre><code>tail</code></pre>');
    });
  });

  describe('image', () => {
    it('embeds an https image (URL is the content)', () => {
      expect(render('[image]https://x.com/a.png[/image]')).toBe(
        '<img src="https://x.com/a.png" alt="chart image">',
      );
    });
    it('drops an image with an unsafe URL', () => {
      expect(render('[image]javascript:alert(1)[/image]')).toBe('');
    });
  });

  describe('unsupported / unknown tags', () => {
    it('strips [u] but keeps its text', () => {
      expect(render('[u]x[/u]')).toBe('x');
    });
    it('strips [color=red] and [size] but keeps text', () => {
      expect(render('[color=red][size=20]x[/size][/color]')).toBe('x');
    });
    it('strips [h1] and generic [code] but keeps text', () => {
      expect(render('[h1]Title[/h1] [code]y[/code]')).toBe('Title y');
    });
    it('shows non-tag brackets verbatim', () => {
      expect(render('array[0] and price[1]')).toBe('array[0] and price[1]');
    });
  });

  describe('security / XSS', () => {
    it('escapes an injected <script> tag', () => {
      const out = render('<script>alert(1)</script>');
      expect(out).not.toContain('<script');
      expect(out).toContain('&lt;script&gt;');
    });
    it('escapes html embedded in a bold tag', () => {
      const out = render('[b]<img src=x onerror=alert(1)>[/b]');
      expect(out).not.toContain('<img src=x');
      expect(out).toContain('&lt;img');
      expect(out).toContain('<strong>');
    });
    it('escapes quotes and cannot break out of an href attribute', () => {
      const out = render('[url=https://x"onmouseover="alert(1)]q[/url]');
      // the escaped quote keeps the payload inside the attribute value
      expect(out).not.toContain('onmouseover="alert');
    });
    it('never emits a raw < from user text', () => {
      expect(render('a<b>c')).not.toContain('<b>');
    });
  });

  describe('[screen] block (M16 §6.6 — swallow entirely)', () => {
    it('drops the tag AND its inner text, unlike the strip-keep-text default', () => {
      const out = render('before\n[screen]\nmarket_cap: >= 2B\nlimit: 50\n[/screen]\nafter');
      expect(out).toContain('before');
      expect(out).toContain('after');
      expect(out).not.toContain('market_cap');
      expect(out).not.toContain('limit');
      expect(out).not.toContain('screen');
    });

    it('is case-insensitive like every other tag', () => {
      expect(render('a\n[SCREEN]\nx: 1\n[/Screen]\nb')).toBe('a<br><br>b');
    });

    it('allows the opening tag to be indented', () => {
      expect(render('a\n   [screen]\nx: 1\n[/screen]\nb')).toBe('a<br>   <br>b');
    });

    it('swallows a block sitting mid-prose without touching the surrounding markup', () => {
      const out = render('[b]Rules[/b]\n[screen]\nsector: Technology\n[/screen]\n[i]done[/i]');
      expect(out).toContain('<strong>Rules</strong>');
      expect(out).toContain('<em>done</em>');
      expect(out).not.toContain('Technology');
    });

    it('an UNCLOSED [screen] falls back to strip-keep-text and never eats the rest', () => {
      // The critical difference from [pine], whose unclosed form swallows to
      // end-of-input. A typo must not make the rest of a description vanish.
      const out = render('intro\n[screen]\nmarket_cap: >= 2B\n\nThe rest of the description.');
      expect(out).toContain('intro');
      expect(out).toContain('The rest of the description.');
      expect(out).toContain('market_cap: &gt;= 2B');
      expect(out).not.toContain('[screen]');
    });

    it('an orphan [/screen] is stripped without eating anything', () => {
      const out = render('alpha [/screen] beta');
      expect(out).toContain('alpha');
      expect(out).toContain('beta');
      expect(out).not.toContain('screen');
    });

    it('swallows every block, not just the first', () => {
      const out = render('a\n[screen]\nx: 1\n[/screen]\nb\n[screen]\ny: 2\n[/screen]\nc');
      expect(out).not.toContain('x: 1');
      expect(out).not.toContain('y: 2');
      expect(out).toContain('a');
      expect(out).toContain('b');
      expect(out).toContain('c');
    });

    it('an INLINE [screen] is a prose mention, not a block — matching the server', () => {
      // The server's opener is line-anchored (apps/screener/criteria.py
      // _OPEN_RE). If the renderer swallowed inline ones anyway, an author who
      // wrote "add a [screen] block" mid-sentence would watch their text vanish
      // while the API reported no block at all.
      const out = render('Add a [screen] block to your description.');
      expect(out).toContain('Add a');
      expect(out).toContain('block to your description.');
      expect(out).not.toContain('[screen]');
    });

    it('does not disturb descriptions that contain no block at all', () => {
      const src = 'A [b]momentum[/b] strategy with array[0] and the word screening.';
      expect(render(src)).toBe(
        'A <strong>momentum</strong> strategy with array[0] and the word screening.',
      );
    });

    it('escapes inner content it keeps when the tag is unclosed (no XSS bypass)', () => {
      const out = render('[screen]\n<script>alert(1)</script>');
      expect(out).not.toContain('<script>');
      expect(out).toContain('&lt;script&gt;');
    });
  });

  describe('realistic combined description', () => {
    it('renders a mixed document correctly', () => {
      const src =
        'A [b]momentum[/b] strategy.\n\n' +
        'Signals:\n' +
        '[list][*]EMA cross[*]RSI filter[/list]\n' +
        'See [url=https://example.com/docs]the docs[/url].';
      const out = render(src);
      expect(out).toContain('<strong>momentum</strong>');
      expect(out).toContain('<ul><li>EMA cross</li><li>RSI filter</li></ul>');
      expect(out).toContain(
        '<a href="https://example.com/docs" target="_blank" rel="nofollow noopener noreferrer">the docs</a>',
      );
      expect(out).not.toContain('[');
      expect(out).not.toContain('[/');
    });
  });
});
