import { describe, expect, it } from 'vitest';
import type { ConsoleContext } from '@/api/consoleContext';
import { canManageNetwork, policyChoices } from './policyChoices';
describe('network governance choices and access', () => {
  it('requires all actual access/action flags, not a role name', () => {
    const context = { roles: [{ code: 'admin' }], access: { policies: true, permissions: true }, actions: { manage_policy: true, propose_change: true } } as ConsoleContext;
    expect(canManageNetwork(context)).toBe(true);
    expect(canManageNetwork()).toBe(false);
    for (const key of ['policies', 'permissions'] as const) expect(canManageNetwork({ ...context, access: { ...context.access, [key]: false } })).toBe(false);
    for (const key of ['manage_policy', 'propose_change'] as const) expect(canManageNetwork({ ...context, actions: { ...context.actions, [key]: false } })).toBe(false);
  });
  it('retains valid IDs/names without interpreting prototype names', () => {
    expect(policyChoices([{ id: '__proto__', name: 'constructor', version: 1, secret: 'ignored' }])).toEqual({ items: [{ id: '__proto__', name: 'constructor', version: 1 }], invalidCount: 0 });
  });
  it('counts malformed and duplicate records instead of selectable fake values', () => {
    const row = { id: 'p', name: 'Policy', version: 1 };
    const input = [row, row, null, { ...row, id: 'other', version: 0 }, { ...row, name: {} }];
    expect(policyChoices(input)).toEqual({ items: [], invalidCount: 5 });
    expect(input).toHaveLength(5);
  });
  it('excludes every occurrence of an ambiguous ID regardless of version or order', () => {
    const first = { id: 'p', name: 'First', version: 1 };
    const second = { id: 'p', name: 'Second', version: 2 };
    const unique = { id: 'unique', name: 'Unique', version: 1 };
    for (const rows of [[first, unique, second], [second, unique, first]]) {
      expect(policyChoices(rows)).toEqual({ items: [unique], invalidCount: 2 });
    }
  });
  it('does not trust a valid-looking duplicate when another occurrence is malformed', () => {
    expect(policyChoices([
      { id: 'p', name: 'Valid', version: 1 },
      { id: 'p', version: null },
    ])).toEqual({ items: [], invalidCount: 2 });
  });
});
