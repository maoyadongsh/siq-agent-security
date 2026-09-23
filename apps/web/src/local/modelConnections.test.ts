import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isModelConnections, isModelConnectionResult } from './modelConnections';
const catalog = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-model-connections.json', import.meta.url), 'utf8'));
const result = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-model-connection-result.json', import.meta.url), 'utf8'));
describe('model configuration and service observations', () => {
  it('accepts shared Go samples without promoting listings to inference', () => { expect(isModelConnections(catalog)).toBe(true); expect(isModelConnectionResult(result, catalog.items[0])).toBe(true); });
  it('rejects ambiguous selections and false capabilities', () => {
    expect(isModelConnections({ ...catalog, network_requested: true })).toBe(false);
    expect(isModelConnections({ ...catalog, items: [catalog.items[0], catalog.items[0]] })).toBe(false);
    expect(isModelConnections({ ...catalog, items: [{ ...catalog.items[0], state: 'credential_unavailable', can_check: true }] })).toBe(false);
    for (const patch of [{ id: 'another' }, { fingerprint: 'a'.repeat(64) }, { inference_verified: true }, { status: 'completed' }]) expect(isModelConnectionResult({ ...result, ...patch }, catalog.items[0])).toBe(false);
  });
});
