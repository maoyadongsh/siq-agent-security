import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isSkillActivated, isSkillRuntimeReadiness, matchesInstalledReadiness } from './skillRuntime';
const sample = (name: string) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/local-skill-install-${name}.v1.sample.json`, import.meta.url), 'utf8'));
describe('installed permission readiness', () => {
  it('accepts signed Go output and rejects mismatched authority and false protection', () => {
    const r = sample('runtime-readiness');
    expect(isSkillRuntimeReadiness(r, r.install_id, r.grant.grant_id)).toBe(true);
    for (const patch of [{ status: 'protected' }, { state_revision: r.state_revision + 1 }, { binding: null }, { runtime_verified: true },
      { grant: { ...r.grant, status: 'revoked' } }, { grant: { ...r.grant, facts: [{}] } },
      { binding: { ...r.binding, install_id: 'sin-' + 'f'.repeat(64) } }, { binding: { ...r.binding, approved_signature: 'f'.repeat(128) } }]) {
      expect(isSkillRuntimeReadiness({ ...r, ...patch })).toBe(false);
    }
    expect(isSkillRuntimeReadiness(r, 'sin-' + 'f'.repeat(64))).toBe(false);
    expect(isSkillRuntimeReadiness(r, undefined, 'other')).toBe(false);
    expect(isSkillRuntimeReadiness({ ...r, binding: null, status: 'not_prepared', state_revision: r.binding.approved_revision })).toBe(true);
    expect(isSkillRuntimeReadiness({ ...r, status: 'incomplete', state_revision: r.binding.approved_revision })).toBe(true);
    expect(isSkillRuntimeReadiness({ ...r, status: 'incomplete' })).toBe(false);
    expect(isSkillRuntimeReadiness({ ...r, binding: null, status: 'no_tools' })).toBe(true);
  });
  it('matches exact installation, source, instance, permissions and approved revision', () => {
    const r = sample('runtime-readiness'), b = r.binding, v = sample('view');
    v.install_id = r.install_id; v.operation.signature = b.operation_signature;
    Object.assign(v.plan, { signature: b.plan_signature, grant_id: b.grant_id, grant_signature: b.approved_signature,
      grant_revision: b.approved_revision, grant_permission_digest: b.permission_digest, instance_id: b.instance_id, source: b.source });
    expect(matchesInstalledReadiness(r, v)).toBe(true);
    for (const patch of [{ grant_id: 'other' }, { instance_id: 'hi-' + 'f'.repeat(32) }, { grant_revision: 99 },
      { grant_permission_digest: 'f'.repeat(64) }, { source: { ...b.source, artifact_digest: 'f'.repeat(64) } }]) {
      expect(matchesInstalledReadiness(r, { ...v, plan: { ...v.plan, ...patch } })).toBe(false);
    }
    expect(matchesInstalledReadiness(r, { ...v, operation: null })).toBe(false);
  });
  it('accepts an activation only for its original operation and explicit actor', () => {
    const out = sample('activated'), req = sample('activate');
    expect(isSkillActivated(out, out.binding.install_id, req)).toBe(true);
    expect(isSkillActivated(out, out.binding.install_id, { ...req, actor_id: 'different' })).toBe(false);
    expect(isSkillActivated({ ...out, runtime_verified: true }, out.binding.install_id, req)).toBe(false);
    expect(isSkillActivated({ ...out, state_revision: 999 }, out.binding.install_id, req)).toBe(false);
  });
});
