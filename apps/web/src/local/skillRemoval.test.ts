import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isSkillRemovalView, skillRemoveRequest } from './skillRemoval';
const sample = (name: string) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/local-skill-install-${name}.v1.sample.json`, import.meta.url), 'utf8'));
describe('explicit installed Skill removal', () => {
  it('accepts Go completion and rejects mixed records or false completion', () => {
    const v = sample('removal-view'), id = v.record.install_id;
    expect(isSkillRemovalView(v, id)).toBe(true);
    expect(isSkillRemovalView(v, 'sin-' + 'f'.repeat(64))).toBe(false);
    for (const patch of [{ result: null }, { claim: null }, { state_revision: 1 }, { status: 'protected' }, { status: 'cleanup_pending' }, { will_revoke_grant: false }, { binding_signature: 'f'.repeat(128) }]) {
      expect(isSkillRemovalView({ ...v, ...patch }, id)).toBe(false);
    }
    for (const patch of [{ target_absent: false }, { grant_revoked: false }, { removal_claim_signature: 'e'.repeat(128) }, { install_id: 'sin-' + 'f'.repeat(64) }, { actor_id: 'different' }]) {
      expect(isSkillRemovalView({ ...v, result: { ...v.result, ...patch } }, id)).toBe(false);
    }
    expect(() => skillRemoveRequest(v, 'human')).toThrow();
  });
  it('requires original retry scope and distinguishes authority states', () => {
    const completed = sample('removal-view'), c = completed.claim, g = sample('runtime-readiness').grant;
    const grant = { ...g, grant_id: c.grant_id, signature: c.grant_signature, subject: { type: 'agent_instance', id: completed.record.plan.instance_id.replace('hi-', 'hri-') } };
    const pending = { ...completed, result: null, grant, state_revision: c.grant_revision, status: 'revocation_pending' };
    const id = completed.record.install_id;
    expect(isSkillRemovalView(pending, id)).toBe(true);
    expect(isSkillRemovalView({ ...pending, state_revision: c.grant_revision + 1 }, id)).toBe(false);
    expect(isSkillRemovalView({ ...pending, status: 'cleanup_pending' }, id)).toBe(false);
    const cleanup = { ...pending, grant: { ...grant, status: 'revoked' }, state_revision: c.grant_revision + 1, status: 'cleanup_pending' };
    expect(isSkillRemovalView(cleanup, id)).toBe(true);
    expect(skillRemoveRequest(cleanup, 'different-current-actor')).toEqual(sample('remove'));
    const preview = { ...pending, claim: null, status: 'not_requested' };
    expect(isSkillRemovalView(preview, id)).toBe(true);
    expect(skillRemoveRequest(preview, ' new-human ').actor_id).toBe('new-human');
    const retained = { ...pending, status: 'cleanup_pending', will_revoke_grant: false, retained_install_id: 'sin-' + 'b'.repeat(64), binding_signature: 'c'.repeat(128), claim: { ...c, revoke_grant: false, retained_install_id: 'sin-' + 'b'.repeat(64), binding_signature: 'c'.repeat(128) } };
    expect(isSkillRemovalView(retained, id)).toBe(true);
    expect(isSkillRemovalView({ ...retained, retained_install_id: id, claim: { ...retained.claim, retained_install_id: id } }, id)).toBe(false);
  });
});
