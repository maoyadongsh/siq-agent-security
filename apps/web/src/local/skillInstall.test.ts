import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { installDirectoryValid, isSkillInstallCreated, isSkillInstallPlan, matchesInstallAuthority, isSkillInstallView } from './skillInstall';
import type { Grant } from './types';

const sample = (name: string) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/local-skill-install-${name}.v1.sample.json`, import.meta.url), 'utf8'));
describe('installation preview binding', () => {
  it('accepts Go fixtures and rejects altered request, target and authority', () => {
    const created = sample('plan-created'); const request = sample('stage-create'); const p = created.plan;
    expect(isSkillInstallPlan(p)).toBe(true);
    expect(isSkillInstallCreated(created, request)).toBe(true);
    const draftId = 'grt-d-' + 'e'.repeat(64);
    expect(isSkillInstallCreated({ ...created, plan: { ...p, grant_id: draftId } }, { ...request, grant_id: draftId })).toBe(true);
    for (const patch of [{ directory_name: 'other' }, { instance_id: 'hi-' + 'f'.repeat(32) }, { actor_id: 'other' }, { grant_revision: 99 }, { request_id: 'is-' + 'f'.repeat(32) }]) {
      expect(isSkillInstallCreated({ ...created, plan: { ...p, ...patch } }, request)).toBe(false);
    }
    const g: Grant = { grant_id: p.grant_id, state_revision: p.grant_revision, signature: p.grant_signature,
      status: 'approved', platform: 'hermes', subject: { type: 'agent_instance', id: p.instance_id.replace(/^hi-/, 'hri-') },
      admission_id: 'adm-si-' + 'a'.repeat(64), enforcement_mode: 'block', created_at: p.created_at };
    expect(matchesInstallAuthority(p, g, p.source)).toBe(true);
    expect(matchesInstallAuthority(p, { ...g, status: 'revoked' }, p.source)).toBe(false);
    expect(matchesInstallAuthority(p, { ...g, signature: 'f'.repeat(128) }, p.source)).toBe(false);
    expect(matchesInstallAuthority(p, g, { ...p.source, artifact_digest: 'f'.repeat(64) })).toBe(false);
    expect(matchesInstallAuthority(p, g, { ...p.source, analysis_sha256: 'f'.repeat(64) })).toBe(false);
  });
  it('rejects installed claims, malformed metadata, over-limit contents and invalid lifetimes', () => {
    const p = sample('plan');
    for (const patch of [{ installed: true }, { runtime_verified: true }, { file_count: 2001 }, { total_bytes: 67108865 },
      { grant_signature: 'bad' }, { signature: null }, { directory_name: '../escape' }, { expires_at: 'bad' }, { expires_at: p.created_at }]) {
      expect(isSkillInstallPlan({ ...p, ...patch })).toBe(false);
    }
    expect(isSkillInstallPlan({ ...p, file_count: 2000, total_bytes: 67108864 })).toBe(true);
  });
  it('keeps portable directory names and reserved device names aligned with Go', () => {
    for (const value of ['a', 'a'.repeat(64), 'com10', 'my-skill']) expect(installDirectoryValid(value)).toBe(true);
    for (const value of ['', 'a'.repeat(65), '../escape', 'a/b', 'a\\b', 'con', 'com1', 'lpt9', 'aux', 'nul', '-a', 'a-', 'UPPER', 'a.b', 'name\n', 'name\r']) expect(installDirectoryValid(value)).toBe(false);
  });
});

describe('installation result binding', () => {
  it('accepts signed Go outcome and incomplete projection, rejects mismatched or invented protection', () => {
    const v = sample('view'); const id = v.install_id;
    expect(isSkillInstallView(v, id)).toBe(true);
    expect(isSkillInstallView({ ...v, operation: null, status: 'recovery_required' }, id)).toBe(true);
    expect(isSkillInstallView({ ...v, operation: null }, id)).toBe(false);
    expect(isSkillInstallView(v, 'sin-' + 'f'.repeat(64))).toBe(false);
    for (const patch of [{ install_id: 'sin-' + 'f'.repeat(64) }, { plan_id: 'sip-' + 'f'.repeat(64) },
      { claim_signature: 'f'.repeat(128) }, { runtime_verified: true }, { signature: null },
      { status: 'protected' }, { recorded_at: 'bad' }, { actor_id: '' }]) {
      expect(isSkillInstallView({ ...v, operation: { ...v.operation, ...patch } }, id)).toBe(false);
    }
    expect(isSkillInstallView({ ...v, status: 'rolled_back' }, id)).toBe(false);
    expect(isSkillInstallView({ ...v, status: 'rolled_back', operation: { ...v.operation, status: 'rolled_back' } }, id)).toBe(true);
  });
});
