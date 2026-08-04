/**
 * Render a TradingView "script description" — a plain-text body that uses
 * TradingView's BBCode-style markup — as a safe HTML fragment for `[innerHTML]`.
 *
 * The stored DESC/.txt file is NEVER modified: this is a display-only transform
 * applied between the `descText()` signal and the DOM.
 *
 * ── Security model (mirrors the guides P2-12 pattern) ──────────────────────────
 * Every run of user text is HTML-escaped FIRST, so no user-supplied `<`/`>`/`&`
 * can ever reach the DOM; only a fixed, self-built whitelist of tags is then
 * emitted. The returned value is a plain `string` (NOT a `SafeHtml`), so when it
 * is bound with `[innerHTML]` Angular's default sanitizer still runs as a second,
 * independent layer. We deliberately do NOT call `bypassSecurityTrustHtml`.
 *
 * ── Supported tags (TradingView "Writing/Publishing scripts" docs) ─────────────
 *   [b]…[/b]                  → <strong>       bold
 *   [i]…[/i]                  → <em>           italic
 *   [s]…[/s]                  → <s>            strikethrough
 *   [url=https://x]label[/url]→ <a>            link (http/https/site-relative only)
 *   [list]…[/list]            → <ul>           bulleted list
 *   [list=1]…[/list]          → <ol>           numbered list
 *   [*]                       → <li>           list item (self-closing, no [/*])
 *   [quote]…[/quote]          → <blockquote>   block quote
 *   [pine]…[/pine]            → <pre><code>    code block (literal, keeps `close[1]`)
 *   [image]https://x[/image]  → <img>          embedded image (http/https only)
 *   [screen]…[/screen]        → (nothing)      M16 screening criteria — swallowed
 *                                              ENTIRELY (tag + inner text); the
 *                                              Screening panel renders them.
 *
 * Unknown / unsupported BBCode ([u], [color], [size], [font], [h1]-[h6], generic
 * [code], [img], [table], [center], …) is stripped while keeping its inner text —
 * matching how TradingView itself drops these from descriptions. Bracket runs
 * that are not a recognised tag (e.g. `array[0]`) are shown verbatim.
 *
 * Out of scope: the `$SYMBOL` auto-link sigil and the legacy [chart]/[symbol]
 * tags — those are cross-site symbol links, not visual text formatting.
 */

const ESCAPE_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ESCAPE_MAP[c]);
}

/**
 * Allow only `http(s)://…` and site-relative `/path` URLs; reject `javascript:`,
 * `data:`, protocol-relative `//host`, etc. Input is already HTML-escaped, so the
 * returned value is safe to drop straight into an `href`/`src` attribute.
 */
function safeUrl(escapedUrl: string): string | null {
  const u = escapedUrl.trim();
  if (!u) return null;
  if (/^https?:\/\//i.test(u)) return u;
  if (/^\/(?![/\\])/.test(u)) return u; // "/path", but not "//host" or "/\host" (both resolve cross-origin)
  return null;
}

type Frame =
  | { kind: 'inline'; bb: string; close: string }
  | { kind: 'list'; close: string }
  | { kind: 'li'; close: string }
  | { kind: 'quote'; close: string };

const INLINE: Record<string, { open: string; close: string }> = {
  b: { open: '<strong>', close: '</strong>' },
  i: { open: '<em>', close: '</em>' },
  s: { open: '<s>', close: '</s>' },
};

/** Newlines in ordinary text become <br>; block-adjacent ones are cleaned up later. */
function textToHtml(escaped: string): string {
  return escaped.replace(/\r\n|\r|\n/g, '<br>');
}

/**
 * Drop <br>s that sit against a block boundary so lists/quotes don't gain blank
 * rows. Both patterns are linear: the first matches a single <br> pinned by a
 * lookahead (no `(?:<br>)+` quantifier that could backtrack quadratically over a
 * long blank-line run — a ReDoS-class freeze); the second is anchored to a
 * block-open tag so its `+` only fires once per block, never per position.
 */
function cleanupBlockBreaks(html: string): string {
  const BLOCK = 'ul|ol|li|blockquote|pre';
  return html
    .replace(new RegExp(`<br>[ \\t]*(?=</?(?:${BLOCK})\\b)`, 'g'), '')
    .replace(new RegExp(`(<(?:${BLOCK})>)(?:[ \\t]*<br>)+`, 'g'), '$1');
}

/**
 * Is `idx` the first non-blank position on its line? Walks back over spaces and
 * tabs only, so it is O(indent) per call, not O(n).
 */
function atLineStart(src: string, idx: number): boolean {
  let k = idx - 1;
  while (k >= 0 && (src[k] === ' ' || src[k] === '\t')) {
    k--;
  }
  return k < 0 || src[k] === '\n';
}

export function renderTradingViewDescription(raw: string): string {
  if (!raw) {
    return '';
  }
  const src = escapeHtml(raw); // escape EVERYTHING before any tag is produced
  const n = src.length;
  const out: string[] = [];
  const stack: Frame[] = [];
  const emit = (s: string) => out.push(s);

  /** Pop-and-close frames from the top down to (and including) the first match. */
  const closeUntil = (match: (f: Frame) => boolean): boolean => {
    let idx = -1;
    for (let k = stack.length - 1; k >= 0; k--) {
      if (match(stack[k])) {
        idx = k;
        break;
      }
    }
    if (idx === -1) {
      return false;
    }
    while (stack.length > idx) {
      emit(stack.pop()!.close);
    }
    return true;
  };

  /** Close any open inline tags (b/i/s/a) before a block opens — a block element
   *  inside <strong>/<em> is invalid HTML. A nested list ([*] then [list]) is
   *  fine: <li> is not inline, so it is left open. */
  const closeOpenInline = () => {
    while (stack.length && stack[stack.length - 1].kind === 'inline') {
      emit(stack.pop()!.close);
    }
  };

  let i = 0;
  while (i < n) {
    if (src[i] !== '[') {
      let j = src.indexOf('[', i);
      if (j === -1) {
        j = n;
      }
      emit(textToHtml(src.slice(i, j)));
      i = j;
      continue;
    }

    const rest = src.slice(i);

    // [pine] … [/pine] — raw code block; content is NOT re-tokenised so literal
    // brackets (Pine's `close[1]` history operator) survive verbatim.
    const pine = /^\[pine\]([\s\S]*?)\[\/pine\]/i.exec(rest);
    if (pine) {
      emit(`<pre><code>${pine[1]}</code></pre>`);
      i += pine[0].length;
      continue;
    }
    const pineOpen = /^\[pine\]/i.exec(rest);
    if (pineOpen) {
      emit(`<pre><code>${src.slice(i + pineOpen[0].length)}</code></pre>`);
      i = n;
      continue;
    }

    // [screen] … [/screen] — machine-readable screening criteria (M16 §6.1).
    // SWALLOWED ENTIRELY: the tag *and* its inner text are dropped, unlike the
    // strip-keep-text default, so the criteria the server parses do not also
    // double-render as prose (AC-16-10). The panel renders them as chips.
    //
    // The opening tag must START ITS OWN LINE, matching the server parser
    // exactly (`_OPEN_RE` in apps/screener/criteria.py). A `[screen]` inside a
    // sentence is a mention, not a block — the authoring guide tells people to
    // "add a [screen] block", and if the two layers disagreed about that, an
    // inline mention would be swallowed from the prose while the server
    // reported no block, silently eating the author's text.
    //
    // Note the deliberate difference from [pine] above: an UNCLOSED [screen]
    // does NOT swallow to end-of-input. It falls through to the generic
    // tokenizer, which strips the marker and keeps the following text — a
    // typo'd tag must never make the rest of someone's description vanish.
    const screen = /^\[screen\]([\s\S]*?)\[\/screen\]/i.exec(rest);
    if (screen && atLineStart(src, i)) {
      i += screen[0].length;
      continue;
    }

    // [image] url [/image] — the URL is the tag CONTENT (opposite of [url]).
    const img = /^\[image\]([\s\S]*?)\[\/image\]/i.exec(rest);
    if (img) {
      const url = safeUrl(img[1]);
      if (url) {
        // No loading="lazy": Angular's [innerHTML] sanitizer strips unknown attrs
        // and logs a dev-mode warning on every render. src/alt are on its allowlist.
        emit(`<img src="${url}" alt="chart image">`);
      }
      i += img[0].length;
      continue;
    }

    // Generic token: [/tag] | [tag] | [tag=value] | [*]
    const tok = /^\[(\/?)([a-zA-Z*][a-zA-Z0-9]*)(?:=([^\]]*))?\]/.exec(rest);
    if (!tok) {
      emit('['); // lone bracket — literal
      i += 1;
      continue;
    }
    const closing = tok[1] === '/';
    const name = tok[2].toLowerCase();
    const attr = tok[3];
    i += tok[0].length;

    if (name === '*') {
      if (closing) {
        continue; // there is no [/*]; ignore it
      }
      // List item marker (self-closing). Only meaningful inside a list: close the
      // previous <li> and any inline tags left open in it, then open a new <li>.
      let listIdx = -1;
      for (let k = stack.length - 1; k >= 0; k--) {
        if (stack[k].kind === 'list') {
          listIdx = k;
          break;
        }
      }
      if (listIdx !== -1) {
        while (stack.length > listIdx + 1) {
          emit(stack.pop()!.close);
        }
        emit('<li>');
        stack.push({ kind: 'li', close: '</li>' });
      }
      continue;
    }

    if (INLINE[name]) {
      if (closing) {
        closeUntil((f) => f.kind === 'inline' && f.bb === name);
      } else {
        emit(INLINE[name].open);
        stack.push({ kind: 'inline', bb: name, close: INLINE[name].close });
      }
      continue;
    }

    if (name === 'url') {
      if (closing) {
        closeUntil((f) => f.kind === 'inline' && f.bb === 'url');
      } else {
        const url = attr != null ? safeUrl(attr) : null;
        if (url) {
          emit(`<a href="${url}" target="_blank" rel="nofollow noopener noreferrer">`);
          stack.push({ kind: 'inline', bb: 'url', close: '</a>' });
        } else {
          // No valid URL → show the label as plain text, but still swallow the
          // matching [/url] via a no-op frame.
          stack.push({ kind: 'inline', bb: 'url', close: '' });
        }
      }
      continue;
    }

    if (name === 'list') {
      if (closing) {
        closeUntil((f) => f.kind === 'list');
      } else {
        closeOpenInline();
        const ordered = (attr ?? '').trim() === '1';
        emit(ordered ? '<ol>' : '<ul>');
        stack.push({ kind: 'list', close: ordered ? '</ol>' : '</ul>' });
      }
      continue;
    }

    if (name === 'quote') {
      if (closing) {
        closeUntil((f) => f.kind === 'quote');
      } else {
        closeOpenInline();
        emit('<blockquote>');
        stack.push({ kind: 'quote', close: '</blockquote>' });
      }
      continue;
    }

    // Unknown / unsupported tag → strip the marker, keep the inner text.
  }

  while (stack.length) {
    emit(stack.pop()!.close);
  }

  return cleanupBlockBreaks(out.join(''));
}
