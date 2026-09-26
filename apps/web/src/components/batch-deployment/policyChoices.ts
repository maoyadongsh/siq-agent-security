import type { ConsoleContext } from '@/api/consoleContext';
export function canManageNetwork(context?: ConsoleContext): boolean {
  return !!context && context.access.permissions && context.access.policies
    && context.actions.manage_policy && context.actions.propose_change;
}
export interface PolicyChoice { id: string; name: string; version: number }
export function policyChoices(rows: unknown[]): { items: PolicyChoice[]; invalidCount: number } {
  const items: PolicyChoice[] = [];
  // A duplicate identity makes both labels ambiguous, even if one row is malformed.
  const counts = new Map<string, number>();
  for (const row of rows) {
    if (!row || typeof row !== 'object' || Array.isArray(row)) continue;
    const id = (row as Record<string, unknown>).id;
    if (typeof id === 'string') counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  let invalidCount = 0;
  for (const row of rows) {
    if (!row || typeof row !== 'object' || Array.isArray(row)) { invalidCount++; continue; }
    const value = row as Record<string, unknown>;
    if (typeof value.id !== 'string' || !value.id || value.id.length > 64 || counts.get(value.id) !== 1
      || typeof value.name !== 'string' || !value.name || value.name.length > 128
      || typeof value.version !== 'number' || !Number.isSafeInteger(value.version) || value.version < 1) { invalidCount++; continue; }
    items.push({ id: value.id, name: value.name, version: value.version });
  }
  return { items, invalidCount };
}
