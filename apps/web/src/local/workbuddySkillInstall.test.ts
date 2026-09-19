import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { isSkillInstallCreated, isSkillInstallPlan, isSkillInstallView, isSkillInstallationTargets, matchesInstallAuthority, sameInstallTarget, skillInstallRequest, skillInstallScopeLabel } from './skillInstall';
import { isSkillInstallationCatalog, isSkillInstallationInspection, isSkillInstallationRecord } from './skillInspection';
import { isSkillRemovalView } from './skillRemoval';
import { isSkillRuntimeReadiness, matchesInstalledReadiness } from './skillRuntime';
import { isSkillUpdateComparison, isSkillUpdateCreated, isSkillUpdatePlan, isSkillUpdateView } from './skillUpdate';
import { isImportPermissionResult } from './importPermissions';
import { resourceFilesystemConfirmation, supportsWindowsGrantResources } from './filesystemProfile';

// Synthetic public-key contract vectors; these do not assert native installation.
const sample = (name: string) => JSON.parse(readFileSync(new URL(`../../../agentshield/testdata/contracts/${name}.sample.json`, import.meta.url), 'utf8'));
const install = (name: string, version = 2) => sample(`local-skill-install-${name}.v${version}`);
const update = (name: string) => sample(`local-skill-update-${name}.v2`);
const clone = <T,>(value: T): T => structuredClone(value);

describe('WorkBuddy scoped installation contracts', () => {
  it('requires an explicit available user or project target without a user-root fallback', () => {
    const catalog = install('targets', 1), readiness = install('runtime-readiness');
    const grant = { ...readiness.grant, state_revision: readiness.binding.approved_revision };
    expect(isSkillInstallationTargets(catalog, catalog.instance_id)).toBe(true);
    for (const target of catalog.targets) {
      const req = skillInstallRequest(grant, 'is-' + 'd'.repeat(32), 'example', 'human', catalog, target.target_id);
      expect(req).toMatchObject({ schema_version: 'local-skill-install-stage-create/v2', target_id: target.target_id });
    }
    for (const targetId of ['', 'sit-' + 'f'.repeat(64)]) expect(skillInstallRequest(grant, 'is-' + 'd'.repeat(32), 'example', 'human', catalog, targetId)).toBeNull();
    const unavailable = { ...catalog, targets: catalog.targets.map((t: object) => ({ ...t, available: false, error_code: 'target_unavailable' })) };
    expect(skillInstallRequest(grant, 'is-' + 'd'.repeat(32), 'example', 'human', unavailable, catalog.targets[0].target_id)).toBeNull();
    expect(skillInstallRequest(grant, 'is-' + 'd'.repeat(32), 'example', 'human', null, catalog.targets[0].target_id)).toBeNull();
    const legacyGrant = { ...grant, platform: 'hermes', schema_version: undefined, filesystem_profile: undefined, filesystem_bindings: undefined };
    const legacy = skillInstallRequest(legacyGrant, 'is-' + 'd'.repeat(32), 'example', 'human', null, '');
    expect(legacy).toMatchObject({ schema_version: 'local-skill-install-stage-create/v1' });
    expect(legacy).not.toHaveProperty('target_id');
    expect(skillInstallRequest({ ...legacyGrant, platform: 'workbuddy' }, 'is-' + 'd'.repeat(32), 'example', 'human', catalog, catalog.targets[0].target_id)).toBeNull();
  });

  it('rejects wrong instances, ambiguous targets, unsupported profiles and private path disclosure', () => {
    const catalog = install('targets', 1), first = catalog.targets[0];
    for (const patch of [
      { instance_id: 'hi-' + 'f'.repeat(32) }, { target_id: 'hi-' + 'a'.repeat(32) }, { platform: 'codebuddy' },
      { filesystem_profile: 'posix/v1' }, { root_display: 'C:/private' }, { target_display: '\\\\server\\private' },
      { available: false, error_code: null }, { available: true, error_code: 'target_unavailable' }, { root_identity_digest: 'a'.repeat(64) },
    ]) expect(isSkillInstallationTargets({ ...catalog, targets: [{ ...first, ...patch }] }, catalog.instance_id)).toBe(false);
    expect(isSkillInstallationTargets({ ...catalog, targets: [first, first] }, catalog.instance_id)).toBe(false);
    expect(isSkillInstallationTargets({ ...catalog, targets: [first, { ...first, target_id: 'sit-' + 'f'.repeat(64) }] }, catalog.instance_id)).toBe(false);
    expect(isSkillInstallationTargets({ ...catalog, platform_changes: true }, catalog.instance_id)).toBe(false);
  });

  it('accepts both scopes and binds plan creation to the selected target and version', () => {
    const created = install('plan-created'), req = install('stage-create'), plan = created.plan;
    expect(isSkillInstallPlan(plan)).toBe(true);
    expect(isSkillInstallPlan(sample('local-skill-install-plan.v2.user'))).toBe(true);
    expect(skillInstallScopeLabel(plan)).toBe('项目级 Skill');
    expect(isSkillInstallCreated(created, req)).toBe(true);
    expect(isSkillInstallCreated(created, { ...req, target_id: 'sit-' + 'f'.repeat(64) })).toBe(false);
    expect(isSkillInstallCreated({ ...created, schema_version: 'local-skill-install-plan-created/v1' }, req)).toBe(false);
    for (const patch of [{ schema_version: 'local-skill-install-plan/v1' }, { platform: 'hermes' }, { target_ref: null }, { target_ref: { ...plan.target_ref, scope: 'cwd' } },
      { target_ref: { ...plan.target_ref, existing_parent_relative_path: 'skills' } }, { target_ref: { ...plan.target_ref, root: 'C:/private' } }]) expect(isSkillInstallPlan({ ...plan, ...patch })).toBe(false);
    const grant = { ...install('runtime-readiness').grant, state_revision: plan.grant_revision };
    expect(matchesInstallAuthority(plan, grant, plan.source)).toBe(true);
    expect(matchesInstallAuthority(plan, { ...grant, schema_version: undefined, filesystem_profile: undefined, filesystem_bindings: undefined }, plan.source)).toBe(false);
    const old = install('plan', 1);
    expect(isSkillInstallPlan(old)).toBe(true);
    expect(isSkillInstallPlan({ ...old, target_ref: plan.target_ref })).toBe(false);
  });

  it('keeps record, result, inspection and removal versions consistent, allowing only catalog mixing', () => {
    const record = install('record'), view = install('view'), inspection = install('inspection'), removal = install('removal-view');
    expect(isSkillInstallationRecord(record)).toBe(true);
    expect(isSkillInstallView(view, view.install_id)).toBe(true);
    expect(isSkillInstallationInspection(inspection, record.install_id)).toBe(true);
    expect(isSkillRemovalView(removal, record.install_id)).toBe(true);
    expect(isSkillInstallationRecord({ ...record, schema_version: 'local-skill-install-record/v1' })).toBe(false);
    expect(isSkillInstallView({ ...view, schema_version: 'local-skill-install-view/v1' }, view.install_id)).toBe(false);
    expect(isSkillInstallationInspection({ ...inspection, schema_version: 'local-skill-install-inspection/v1' }, record.install_id)).toBe(false);
    expect(isSkillRemovalView({ ...removal, schema_version: 'local-skill-install-removal-view/v1' }, record.install_id)).toBe(false);
    const catalog = install('catalog');
    expect(isSkillInstallationCatalog(catalog)).toBe(true);
    expect(isSkillInstallationCatalog({ ...catalog, schema_version: 'local-skill-install-catalog/v1' })).toBe(false);
  });

  it('fixes update scope and roots while allowing a deeper signed parent checkpoint', () => {
    const plan = update('plan'), created = update('plan-created'), view = update('view'), comparison = update('comparison');
    const req = { schema_version: 'local-skill-update-stage-create/v1' as const, request_id: plan.request_id, operation_signature: plan.record.operation.signature,
      candidate_grant_id: plan.candidate_grant_id, expected_candidate_revision: plan.candidate_revision, expected_previous_revision: plan.previous_revision, expected_binding_signature: plan.binding_signature, actor_id: plan.actor_id };
    expect(isSkillUpdatePlan(plan, plan.update_id)).toBe(true);
    expect(isSkillUpdateCreated(created, plan.record.install_id, req)).toBe(true);
    expect(isSkillUpdateComparison(comparison, comparison.record.install_id, { schema_version: 'local-skill-update-compare/v1', operation_signature: comparison.record.operation.signature, candidate_grant_id: comparison.candidate_grant.grant_id, expected_candidate_revision: comparison.candidate_revision })).toBe(true);
    expect(isSkillUpdateView(view, view.update_id)).toBe(true);
    for (const field of ['target_id', 'scope', 'root_locator_digest', 'root_identity_digest', 'config_root_identity_digest']) {
      const changed = clone(view); changed.claim.replacement_plan.target_ref[field] = field === 'scope' ? 'user' : field === 'target_id' ? 'sit-' + 'f'.repeat(64) : 'f'.repeat(64);
      expect(isSkillUpdateView(changed, changed.update_id)).toBe(false);
    }
    const advanced = clone(view); advanced.claim.replacement_plan.target_ref.existing_parent_relative_path = '.codebuddy/skills'; advanced.claim.replacement_plan.target_ref.existing_parent_identity_digest = 'f'.repeat(64);
    expect(isSkillUpdateView(advanced, advanced.update_id)).toBe(true);
    const sameDepthChanged = clone(view); sameDepthChanged.claim.replacement_plan.target_ref.existing_parent_identity_digest = 'f'.repeat(64);
    expect(isSkillUpdateView(sameDepthChanged, sameDepthChanged.update_id)).toBe(false);
    expect(sameInstallTarget(advanced.claim.replacement_plan, view.claim.replacement_plan)).toBe(false);
    for (const changed of [ { ...view, schema_version: 'local-skill-update-view/v1' }, { ...view, claim: { ...view.claim, schema_version: 'local-skill-update-claim/v1' } },
      { ...view, claim: { ...view.claim, replacement_plan: install('plan', 1) } } ]) expect(isSkillUpdateView(changed, view.update_id)).toBe(false);
  });

  it('selects runtime and import response versions from the actual Grant without claiming effective permission', () => {
    const readiness = install('runtime-readiness'), view = install('view');
    expect(isSkillRuntimeReadiness(readiness, view.install_id)).toBe(true);
    expect(matchesInstalledReadiness(readiness, view)).toBe(true);
    expect(isSkillRuntimeReadiness({ ...readiness, schema_version: 'local-skill-install-runtime-readiness/v1' })).toBe(false);
    expect(isSkillRuntimeReadiness({ ...readiness, grant: { ...readiness.grant, filesystem_bindings: { resource: 'bad' } } })).toBe(false);
    expect(isSkillRuntimeReadiness({ ...readiness, grant: { ...readiness.grant, status: 'effective' } })).toBe(false);
    const result = sample('local-skill-import-permission-created.v2');
    const req = { schema_version: 'local-skill-import-permission-create/v1' as const, request_id: 'ip-' + 'd'.repeat(32), instance_id: view.plan.instance_id, artifact_digest: result.source.artifact_digest, analysis_sha256: result.source.analysis_sha256, actor_id: 'human' };
    expect(isImportPermissionResult(result, result.import_id, req)).toBe(true);
    expect(isImportPermissionResult({ ...result, schema_version: 'local-skill-import-permission-created/v1' }, result.import_id, req)).toBe(false);
    expect(isImportPermissionResult({ ...result, grant: { ...result.grant, status: 'effective' } }, result.import_id, req)).toBe(false);
  });

  it('offers Windows resource conversion only for a complete exact imported Skill identity', () => {
    const grant = install('runtime-readiness').grant;
    expect(supportsWindowsGrantResources(grant)).toBe(true);
    expect(resourceFilesystemConfirmation(grant, 'windows-local-drive/v1', true)).toEqual({ profile: 'windows-local-drive/v1', confirmed: true });
    for (const patch of [{ admission_id: 'adm-ordinary' }, { admission_id: 'adm-si-invalid' }, { subject: { type: 'agent_instance', id: 'hri-invalid' } },
      { skill: undefined }, { skill: null }, { skill: { skill_id: 'example' } }, { skill: { ...grant.skill, content_hash: 'bad' } }]) expect(supportsWindowsGrantResources({ ...grant, ...patch })).toBe(false);
    expect(resourceFilesystemConfirmation(grant, 'windows-local-drive/v1', false)).toBeNull();
  });
});

afterEach(() => vi.unstubAllGlobals());
describe('WorkBuddy installation API boundary', () => {
  it('reads only the requested instance and rejects target substitutions without a fallback request', async () => {
    vi.stubGlobal('fetch', vi.fn()); const { localApi } = await import('./api'); const catalog = install('targets', 1);
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(catalog), { status: 200 }));
    await expect(localApi.skillInstallationTargets(catalog.instance_id)).resolves.toEqual(catalog);
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(`/v1/skill-installation-targets?instance_id=${catalog.instance_id}`);
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ ...catalog, instance_id: 'hi-' + 'f'.repeat(32) }), { status: 200 }));
    await expect(localApi.skillInstallationTargets(catalog.instance_id)).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('sends the explicit v2 target and rejects a response for another target', async () => {
    vi.stubGlobal('fetch', vi.fn()); const { localApi } = await import('./api'); const req = install('stage-create'), created = install('plan-created');
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(created), { status: 200 }));
    await expect(localApi.createInstallPlan(req)).resolves.toEqual(created);
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual(req);
    const wrong = clone(created); wrong.plan.target_ref.target_id = 'sit-' + 'f'.repeat(64);
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(wrong), { status: 200 }));
    await expect(localApi.createInstallPlan(req)).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('rejects incomplete v2 or target-bearing v1 requests before sending a mutation', async () => {
    vi.stubGlobal('fetch', vi.fn()); const { localApi } = await import('./api'); const req = install('stage-create');
    const { target_id: _target, ...withoutTarget } = req;
    await expect(localApi.createInstallPlan(withoutTarget)).rejects.toMatchObject({ status: 400 });
    await expect(localApi.createInstallPlan({ ...req, schema_version: 'local-skill-install-stage-create/v1' })).rejects.toMatchObject({ status: 400 });
    await expect(localApi.createInstallPlan({ ...req, target_id: 'C:/private' })).rejects.toMatchObject({ status: 400 });
    expect(fetch).not.toHaveBeenCalled();
  });
});
