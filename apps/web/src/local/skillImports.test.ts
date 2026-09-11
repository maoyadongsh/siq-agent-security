import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isSkillImportList, isSkillImportResult, newImportId } from './skillImports';

const sample = (name: string, version = 1) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/${name}.v${version}.sample.json`, import.meta.url), 'utf8'));

describe('Skill candidate response boundaries', () => {
  it('accepts shared Go outputs while rejecting claimed installation and mismatched request identity', () => {
    const result = sample('local-skill-import-result');
    expect(isSkillImportResult(result, result.import.import_id)).toBe(true);
    expect(isSkillImportResult({ ...result, installed: true }, result.import.import_id)).toBe(false);
    expect(isSkillImportResult(result, 'si-' + 'f'.repeat(32))).toBe(false);
    expect(isSkillImportResult({ ...result, admission: { ...result.admission, verdict: 'approved' } }, result.import.import_id)).toBe(false);
  });
  it('refuses unchecked history as payload proof and hides unverified record fields', () => {
    const list = sample('local-skill-import-list');
    expect(isSkillImportList(list)).toBe(true);
    expect(isSkillImportList({ ...list, items: [{ ...list.items[0], payload_status: 'verified' }] })).toBe(false);
    expect(isSkillImportList({ ...list, items: [{ ...list.items[1], summary: list.items[0].summary }] })).toBe(false);
    expect(isSkillImportList({ ...list, items: [list.items[0], list.items[0]] })).toBe(false);
  });
  it('accepts remote v2 and mixed history but refuses version confusion and invalid archive metadata', () => {
    const result = sample('local-skill-import-result', 2);
    const id = result.import.import_id;
    expect(isSkillImportResult(result, id)).toBe(true);
    expect(isSkillImportResult({ ...result, schema_version: 'local-skill-import-result/v1' }, id)).toBe(false);
    for (const remote of [null, { ...result.import.remote, archive_bytes: 33554433 }, { ...result.import.remote, archive_bytes: 0 },
      { ...result.import.remote, expected_sha256: '0'.repeat(64) }, { ...result.import.remote, archive_sha256: 'invalid' }]) {
      expect(isSkillImportResult({ ...result, import: { ...result.import, remote } }, id)).toBe(false);
    }
    const local = sample('local-skill-import-result');
    expect(isSkillImportResult({ ...local, import: { ...local.import, remote: result.import.remote } }, local.import.import_id)).toBe(false);
    const list = sample('local-skill-import-list', 2);
    expect(isSkillImportList(list)).toBe(true);
    expect(isSkillImportList({ ...list, schema_version: 'local-skill-import-list/v1' })).toBe(false);
  });
  it('generates opaque request IDs without source data', () => {
    const ids = Array.from({ length: 50 }, newImportId);
    expect(ids.every((id) => /^si-[a-f0-9]{32}$/.test(id))).toBe(true);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
