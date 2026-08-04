import { MissingTranslationHandlerParams } from '@ngx-translate/core';
import { AppMissingTranslationHandler } from './missing-translation.handler';

describe('AppMissingTranslationHandler', () => {
  const handler = new AppMissingTranslationHandler();

  it('prefers an explicit default interpolation param', () => {
    const p = { key: 'x.y.z', interpolateParams: { default: 'Fallback message' } } as unknown as MissingTranslationHandlerParams;
    expect(handler.handle(p)).toBe('Fallback message');
  });

  it('humanizes the last key segment — never returns the raw dotted key', () => {
    const p = { key: 'auth.login.error.SESSION_EXPIRED' } as unknown as MissingTranslationHandlerParams;
    const out = handler.handle(p);
    expect(out).toBe('Session expired');
    expect(out).not.toContain('auth.login.error');
  });
});
