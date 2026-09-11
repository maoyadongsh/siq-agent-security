import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { comparisonMatchesPlan, isSkillUpdateComparison, isSkillUpdateCreated, isSkillUpdatePlan, isSkillUpdateView } from './skillUpdate';
const sample = (name: string) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/local-skill-update-${name}.v1.sample.json`, import.meta.url), 'utf8'));
describe('Skill update review and transaction boundaries', () => {
  it('validates comparison without implying candidate approval', () => {
    const c = sample('comparison'), r = sample('compare'), id = c.record.install_id;
    expect(isSkillUpdateComparison(c, id, r)).toBe(true);
    for (const patch of [{ requires_confirmation: false }, { platform_changes: true }, { candidate_revision: 123 }, { content_changes_total: 123 }, { settings_changed: ['unknown'] }, { previous_grant: c.candidate_grant }]) expect(isSkillUpdateComparison({ ...c, ...patch }, id, r)).toBe(false);
    expect(isSkillUpdateComparison({ ...c, content_changes: [{ ...c.content_changes[0], before: null, after: null }] }, id, r)).toBe(false);
    expect(comparisonMatchesPlan(c, sample('plan'))).toBe(false);
  });
  it('binds prepared plan to the exact request and does not renew expiry', () => {
    const p = sample('plan'), req = sample('stage-create');
    expect(isSkillUpdatePlan(p, p.update_id)).toBe(true);
    expect(isSkillUpdateCreated(sample('plan-created'), p.record.install_id, req)).toBe(true);
    expect(isSkillUpdateCreated(sample('plan-created'), p.record.install_id, { ...req, actor_id: 'other' })).toBe(false);
    for (const patch of [{ expires_at: p.created_at }, { requires_confirmation: false }, { revoke_previous_grant: false }, { candidate_grant_id: p.record.plan.grant_id }, { arbitrary: true }]) expect(isSkillUpdatePlan({ ...p, ...patch })).toBe(false);
  });
  it('validates historical aborted result and rejects substituted scope or false success', () => {
    const v = sample('view'), id = v.update_id;
    expect(isSkillUpdateView(v, id)).toBe(true);
    for (const patch of [{ status: 'updated_unverified' }, { result: null }, { update_id: 'sup-' + 'f'.repeat(64) }]) expect(isSkillUpdateView({ ...v, ...patch }, id)).toBe(false);
    expect(isSkillUpdateView({ ...v, claim: { ...v.claim, replacement_plan: { ...v.claim.replacement_plan, directory_name: 'other' } } }, id)).toBe(false);
    expect(isSkillUpdateView({ ...v, result: { ...v.result, claim_signature: 'e'.repeat(128) } }, id)).toBe(false);
    expect(isSkillUpdateView({ ...v, result: { ...v.result, runtime_verified: true } }, id)).toBe(false);
  });
});
