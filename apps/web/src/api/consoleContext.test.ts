import { describe, expect, it } from 'vitest';
import { accessKeys, actionKeys, canVisit, isConsoleContext, routeAccessKey, type ConsoleContext } from './consoleContext';
const sample = { schema_version: 'console-context/v1', evaluated_at: '2026-09-23T01:00:00Z', tenant: { id: 't1', name: '组织一' }, actor: { id: 'u1', type: 'user' }, authentication: 'verified_token', roles: [{ code: 'viewer', label: '只读查看者', description: '只读' }], custom_role_count: 0,
  access: Object.fromEntries(accessKeys.map(k => [k, ['workspace', 'settings', 'agents'].includes(k)])), actions: Object.fromEntries(actionKeys.map(k => [k, false])) } as ConsoleContext;
describe('verified enterprise context', () => {
  it('rejects coercible non-string identity enums', () => {
    expect(isConsoleContext({ ...sample, actor: { ...sample.actor, type: ['user'] } })).toBe(false);
    expect(isConsoleContext({ ...sample, authentication: ['verified_token'] })).toBe(false);
  });
  it('rejects incomplete or malformed identity and permission snapshots', () => {
    expect(isConsoleContext(sample)).toBe(true);
    for (const v of [null, { ...sample, unexpected_token: 'should-not-enter-context' }, { ...sample, access: { ...sample.access, extra: true } }, { ...sample, tenant: null }, { ...sample, schema_version: 'other' }, { ...sample, roles: [null] }, { ...sample, roles: [sample.roles[0], sample.roles[0]] }, { ...sample, evaluated_at: 'invalid' }, { ...sample, access: { agents: true } }, { ...sample, actions: {} }, { ...sample, custom_role_count: -1 }]) expect(isConsoleContext(v)).toBe(false);
  });
  it('requires actual access booleans even when a role label claims administration', () => {
    const misleading = { ...sample, roles: [{ code: 'admin', label: '管理员', description: '' }] };
    expect(canVisit(misleading, '/agents/asset-1?view=candidates')).toBe(true);
    expect(canVisit(misleading, '/environments')).toBe(false);
    expect(canVisit(undefined, '/agents')).toBe(false);
    expect(canVisit(undefined, '/workspace')).toBe(true);
    expect(canVisit(undefined, '/settings')).toBe(true);
    expect(routeAccessKey('/runtime-bindings')).toBe('runtime_bindings');
    expect(canVisit(misleading, '/unknown')).toBe(false);
  });
});
