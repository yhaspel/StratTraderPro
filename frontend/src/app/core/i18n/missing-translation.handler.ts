/** C-FE-2: a MissingTranslationHandler so a missing key never renders as the
 * raw dotted key (e.g. `auth.login.error.UNKNOWN`). Prefers an explicit
 * `default` interpolation param, otherwise humanizes the key's last segment. */
import { MissingTranslationHandler, MissingTranslationHandlerParams } from '@ngx-translate/core';

export class AppMissingTranslationHandler implements MissingTranslationHandler {
  handle(params: MissingTranslationHandlerParams): string {
    const fallback = params.interpolateParams as { default?: string } | undefined;
    if (fallback?.default) {
      return fallback.default;
    }
    const leaf = (params.key?.split('.').pop() ?? params.key ?? '').replace(/[_-]+/g, ' ').trim().toLowerCase();
    return leaf ? leaf.charAt(0).toUpperCase() + leaf.slice(1) : (params.key ?? '');
  }
}
