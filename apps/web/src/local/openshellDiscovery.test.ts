import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isOpenShellTargets, isOpenShellInspection } from './openshellDiscovery';
const catalog = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-openshell-targets.json', import.meta.url), 'utf8'));
const inspected = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-openshell-target-inspection.json', import.meta.url), 'utf8'));
describe('OpenShell discovery boundary', () => {
  it('accepts shared Go read-only samples', () => { expect(isOpenShellTargets(catalog)).toBe(true); expect(isOpenShellInspection(inspected, catalog.items[0], catalog)).toBe(true); });
  it('rejects ambiguous targets and invented authority', () => {
    for (const patch of [{ started_gateway: true }, { items: [catalog.items[0], catalog.items[0]] }, { endpoint_fingerprint: '', can_inspect: true }, { state: 'unconfigured' }]) expect(isOpenShellTargets({ ...catalog, ...patch })).toBe(false);
    for (const patch of [{ sandbox_id: 'other' }, { endpoint_fingerprint: 'a'.repeat(64) }, { enforcement_verified: true }, { state: 'isolated' }]) expect(isOpenShellInspection({ ...inspected, ...patch }, catalog.items[0], catalog)).toBe(false);
  });
});
