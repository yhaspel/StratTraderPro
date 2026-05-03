import { TestBed } from '@angular/core/testing';
import { StrategiesStore } from './strategies.store';
import { Strategy, WebhookConfig } from '../../core/models/strategies.models';

function _strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: overrides.id ?? 's1',
    name: overrides.name ?? 'Demo',
    slug: overrides.slug ?? 'demo',
    description_short: '',
    is_system: overrides.is_system ?? false,
    is_enabled: overrides.is_enabled ?? true,
    is_community_tested: false,
    type: overrides.is_system ? 'system' : 'user',
    has_webhook_config: false,
    created_at: '2026-05-03T00:00:00Z',
    updated_at: '2026-05-03T00:00:00Z',
    files: [],
    ...overrides,
  };
}

describe('StrategiesStore', () => {
  let store: StrategiesStore;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    store = TestBed.inject(StrategiesStore);
  });

  it('starts empty', () => {
    expect(store.count()).toBe(0);
    expect(store.systemCount()).toBe(0);
  });

  it('counts system + user strategies separately', () => {
    store.setStrategies([
      _strategy({ id: 'sys-a', is_system: true }),
      _strategy({ id: 'sys-b', is_system: true }),
      _strategy({ id: 'usr-a' }),
    ]);
    expect(store.systemCount()).toBe(2);
    expect(store.userCount()).toBe(1);
  });

  it('upsertStrategy replaces existing by id', () => {
    store.setStrategies([_strategy({ id: 'a', name: 'Old' })]);
    store.upsertStrategy(_strategy({ id: 'a', name: 'New' }));
    expect(store.strategies().length).toBe(1);
    expect(store.strategies()[0].name).toBe('New');
  });

  it('removeStrategy filters by id', () => {
    store.setStrategies([_strategy({ id: 'a' }), _strategy({ id: 'b' })]);
    store.removeStrategy('a');
    expect(store.strategies().map(s => s.id)).toEqual(['b']);
  });

  it('webhookConfig signal updates per-strategy and clears reveal-once', () => {
    const cfg: WebhookConfig = {
      version: 1,
      json_schema: {},
      payload_template: {},
      url: 'https://example/x/y/',
      secret: 'topsecret',
      reveal_once: true,
    };
    store.setWebhookConfig('s1', cfg);
    expect(store.webhookConfig('s1')()!.secret).toBe('topsecret');
    store.clearRevealedSecret('s1');
    expect(store.webhookConfig('s1')()!.secret).toBeNull();
    expect(store.webhookConfig('s1')()!.reveal_once).toBe(false);
  });
});
