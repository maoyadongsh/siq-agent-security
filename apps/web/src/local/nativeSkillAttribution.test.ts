import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { receiptSkillAttributionLabel } from './skillAttribution';
import type { Receipt } from './types';

const fixture = (name: string): Receipt => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/${name}`, import.meta.url), 'utf8'));
const skill = () => fixture('native-receipt-with-skill-v3.sample.json');
const noSkill = () => fixture('native-receipt-no-skill-v3.sample.json');

describe('native receipt attribution presentation', () => {
  it('shows the actual Go receipt as call-level context, distinct from effect or current authority', () => {
    const r = skill();
    const label = receiptSkillAttributionLabel(r, true);
    expect(label.trusted).toBe(true);
    expect(label.text).toContain('调用级可信');
    expect(label.detail).toContain(r.native_invocation!.agent_authority.grant_id);
    expect(label.detail).toContain('不证明当前授权仍有效、业务效果或模型指令因果');
    r.action = 'deny';
    expect(receiptSkillAttributionLabel(r, true).trusted).toBe(true);
  });
  it('shows explicit no-Skill proof without creating Skill attribution', () => {
    const label = receiptSkillAttributionLabel(noSkill(), true);
    expect(label.text).toBe('无 Skill · Agent 基线');
    expect(label.trusted).toBe(true);
  });
  it('preserves invocation evidence throughout the actual hold lifecycle', () => {
    const records: Receipt[] = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/native-hold-with-skill-v3.sample.json', import.meta.url), 'utf8'));
    expect(records.map(r => r.record_type)).toEqual(['decision', 'hold_resolution', 'hold_reservation', 'observation']);
    for (const r of records) expect(receiptSkillAttributionLabel(r, true).trusted).toBe(true);
  });
  it.each([false, null, undefined, 'true', 'false', 1])('requires strict backend verification: %s', verified => {
    expect(receiptSkillAttributionLabel(skill(), verified).trusted).toBe(false);
    expect(receiptSkillAttributionLabel(noSkill(), verified).trusted).toBe(false);
  });
  const mutations: [string, (r: Receipt) => void][] = [
    ['missing proof', r => { delete r.native_invocation; }],
    ['legacy schema', r => { r.schema_version = 'runtime-receipt/v2'; }],
    ['unknown schema', r => { Object.assign(r, { schema_version: 'runtime-receipt/v99' }); }],
    ['missing attribution', r => { delete r.skill_attribution; }],
    ['changed binding', r => { r.skill_attribution!.call_binding = 'f'.repeat(64); }],
    ['changed leaf', r => { r.skill_attribution!.context_id = 'sec-' + 'f'.repeat(32); }],
    ['legacy attribution', r => { r.skill_attribution!.evidence_level = 'controlled_task'; }],
    ['unknown attribution', r => { r.skill_attribution!.status = 'unknown'; }],
    ['missing content hash', r => { delete r.skill_attribution!.content_hash; }],
    ['malformed skill name', r => { Object.assign(r.skill_attribution!, { skill_id: 7 }); }],
    ['missing call signature', r => { r.native_invocation!.call_signature = ''; }],
    ['invalid session', r => { r.native_invocation!.session_registration_id = 'unknown'; }],
    ['invalid baseline', r => { r.native_invocation!.agent_authority.grant_digest = 'invalid'; }],
    ['invalid ancestor', r => { r.native_invocation!.contexts[0].context_signature = ''; }],
    ['duplicate contexts', r => { r.native_invocation!.contexts.push(r.native_invocation!.contexts[0]); }],
    ['too many contexts', r => { r.native_invocation!.contexts = Array.from({ length: 9 }, (_, i) => ({ ...r.native_invocation!.contexts[0], context_id: 'sec-' + i.toString(16).padStart(32, '0') })); }],
    ['null contexts', r => { Object.assign(r.native_invocation!, { contexts: null }); }],
    ['null ancestor', r => { Object.assign(r.native_invocation!, { contexts: [null] }); }],
    ['missing no_skill', r => { Object.assign(r.native_invocation!, { no_skill: undefined }); }],
    ['contradictory no_skill', r => { r.native_invocation!.no_skill = true; }],
  ];
  it.each(mutations)('never upgrades %s', (_name, mutate) => {
    const r = skill();
    mutate(r);
    expect(receiptSkillAttributionLabel(r, true).trusted).toBe(false);
  });
  it('rejects a Skill claim added to an explicit no-Skill receipt', () => {
    const r = noSkill();
    r.skill_attribution = skill().skill_attribution;
    expect(receiptSkillAttributionLabel(r, true).trusted).toBe(false);
    Object.assign(r, { skill_attribution: null });
    expect(receiptSkillAttributionLabel(r, true).trusted).toBe(false);
  });
  it('also requires verification before displaying legacy attribution as trusted', () => {
    const r = skill();
    delete r.native_invocation;
    delete r.schema_version;
    r.skill_attribution!.evidence_level = 'controlled_task';
    expect(receiptSkillAttributionLabel(r, true).trusted).toBe(true);
    expect(receiptSkillAttributionLabel(r, false).trusted).toBe(false);
  });
});
