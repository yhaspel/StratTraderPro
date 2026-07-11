/** Runtime config accessor. Reads `window.STP_CONFIG`, which nginx fills in at
 *  serve time from env vars (see docker/nginx.conf.template). Falls back to
 *  empty strings when the config script is absent (e.g. `ng serve` without
 *  nginx). Callers treat empty values as "feature off".
 *
 *  Every value goes through `runtimeValue()`, which additionally treats a
 *  leftover `${VAR}` placeholder as unset — see BUG-004 and core/runtime-config.ts. */
import { Injectable } from '@angular/core';

import { RuntimeConfig, readRuntimeConfig, runtimeValue } from '../runtime-config';

export type { RuntimeConfig };

@Injectable({ providedIn: 'root' })
export class ConfigService {
  private get cfg(): RuntimeConfig {
    return readRuntimeConfig();
  }

  get backendUrl(): string { return runtimeValue(this.cfg.backendUrl); }
  get grafanaUrl(): string { return runtimeValue(this.cfg.grafanaUrl); }
  get sentryDsn(): string { return runtimeValue(this.cfg.sentryDsn); }
  get sentryEnvironment(): string { return runtimeValue(this.cfg.sentryEnvironment) || 'development'; }
  get release(): string { return runtimeValue(this.cfg.release); }
}
