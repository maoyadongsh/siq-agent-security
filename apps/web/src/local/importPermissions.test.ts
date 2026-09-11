import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isImportPermissionResult, isImportPermissionSource } from './importPermissions';

const sample = (kind: string) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/local-skill-import-permission-${kind}.v1.sample.json`, import.meta.url), 'utf8'));

describe('import permission preparation', () => {
  it('accepts the shared Go draft and rejects installed, wrong-content and wrong-instance responses', () => {
    const result = sample('created'); const req = sample('create'); const id = result.import_id;
    expect(isImportPermissionResult(result, id, req)).toBe(true);
    for (const bad of [
      { ...result, installed: true },
      { ...result, source: { ...result.source, artifact_digest: '0'.repeat(64) } },
      { ...result, source: { ...result.source, analysis_sha256: '0'.repeat(64) } },
      { ...result, grant: { ...result.grant, subject: { type: 'agent_instance', id: 'hri-wrong' } } },
      { ...result, grant: { ...result.grant, status: 'effective' } },
      { ...result, state_revision: -1 },
    ]) expect(isImportPermissionResult(bad, id, req)).toBe(false);
    expect(isImportPermissionResult(result, 'si-' + 'f'.repeat(32), req)).toBe(false);
  });
  it('requires all immutable source digests', () => {
    const source = sample('source');
    expect(isImportPermissionSource(source)).toBe(true);
    expect(isImportPermissionSource({ ...source, artifact_digest: 'old-prefix' })).toBe(false);
    expect(isImportPermissionSource({ ...source, analysis_sha256: null })).toBe(false);
    expect(isImportPermissionSource({ ...source, import_id: '../escape' })).toBe(false);
  });
});
