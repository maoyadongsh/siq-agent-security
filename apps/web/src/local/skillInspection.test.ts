import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isSkillInstallationCatalog, isSkillInstallationInspection, isSkillInstallationRecord } from './skillInspection';
const sample = (name: string) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/local-skill-install-${name}.v1.sample.json`, import.meta.url), 'utf8'));
describe('installed Skill historical records and current comparisons', () => {
  it('validates Go history without reinterpreting it as current protection', () => {
    const r = sample('record'), c = sample('catalog');
    expect(isSkillInstallationRecord(r)).toBe(true);
    expect(isSkillInstallationCatalog(c)).toBe(true);
    expect(isSkillInstallationRecord({ ...r, operation: null })).toBe(false);
    expect(isSkillInstallationRecord({ ...r, operation: null, recorded_status: 'recovery_required' })).toBe(true);
    expect(isSkillInstallationRecord({ ...r, operation: { ...r.operation, claim_signature: 'f'.repeat(128) } })).toBe(false);
    expect(isSkillInstallationCatalog({ ...c, items: [r, r] })).toBe(false);
    expect(isSkillInstallationCatalog({ ...c, platform_changes: true })).toBe(false);
    expect(isSkillInstallationCatalog({ ...c, issues: [{ install_id: null, code: 'record_unavailable' }] })).toBe(true);
    expect(isSkillInstallationCatalog({ ...c, issues: [{ install_id: '../../other', code: 'record_unavailable' }] })).toBe(false);
  });
  it('rejects false matched/complete states, malformed changes and target substitution', () => {
    const i = sample('inspection'), id = i.record.install_id;
    expect(isSkillInstallationInspection(i, id)).toBe(true);
    expect(isSkillInstallationInspection(i, 'sin-' + 'f'.repeat(64))).toBe(false);
    for (const patch of [{ platform_changes: true }, { comparison_complete: false }, { target_state: 'protected' }, { target_state: 'changed' }, { changes_total: 1 }, { changes_truncated: true }]) {
      expect(isSkillInstallationInspection({ ...i, ...patch }, id)).toBe(false);
    }
    const change = { path_display: 'SKILL.md', path_digest: 'a'.repeat(64), kind: 'file', change: 'modified' };
    const changed = { ...i, target_state: 'changed', changes: [change], changes_total: 1 };
    expect(isSkillInstallationInspection(changed, id)).toBe(true);
    expect(isSkillInstallationInspection({ ...changed, changes: [{ ...change, path_display: 'unsafe\nname' }] }, id)).toBe(false);
    expect(isSkillInstallationInspection({ ...changed, changes: Array(201).fill(change), changes_total: 201 }, id)).toBe(false);
    expect(isSkillInstallationInspection({ ...changed, changes_total: 201, changes_truncated: true }, id)).toBe(true);
    expect(isSkillInstallationInspection({ ...i, target_state: 'unavailable', comparison_complete: false, issue_code: 'comparison_budget_exceeded' }, id)).toBe(true);
  });
});
