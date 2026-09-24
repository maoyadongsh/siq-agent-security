import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isGatewayCatalog } from './openshellGateways';
const sample = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-openshell-gateways.json', import.meta.url), 'utf8'));
describe('registered gateway selection', () => {
  it('accepts Go projections and distinguishes empty from unreadable', () => {
    expect(isGatewayCatalog(sample)).toBe(true);
    expect(isGatewayCatalog({ ...sample, items: [] })).toBe(true);
    expect(isGatewayCatalog({ ...sample, state: 'unavailable', items: [] })).toBe(true);
    expect(isGatewayCatalog({ ...sample, state: 'unavailable' })).toBe(false);
  });
  it('rejects ambiguous selection and credentials in displayed endpoints', () => {
    for (const patch of [{ started_gateway: true }, { changed_native_selection: true }, { items: [sample.items[0], sample.items[0]] }]) expect(isGatewayCatalog({ ...sample, ...patch })).toBe(false);
    for (const patch of [{ gateway_id: 'external' }, { name: '../escape' }, { configuration_fingerprint: '' }, { endpoint_display: 'https://user:secret@example.org' }, { endpoint_display: 'https://example.org/?token=secret' }]) expect(isGatewayCatalog({ ...sample, items: [{ ...sample.items[0], ...patch }] })).toBe(false);
  });
});
