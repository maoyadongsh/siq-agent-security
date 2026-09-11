import { isImportPermissionSource } from './importPermissions';
import type { SkillActivated, SkillActivateRequest, SkillInstallView, SkillRuntimeBinding, SkillRuntimeReadiness } from './types';
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && !!v.trim();
const sig = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{128}$/.test(v);
const digest = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const revision = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every((k) => k in v);
export function isSkillRuntimeBinding(v: unknown): v is SkillRuntimeBinding {
  return object(v) && exact(v, ['schema_version', 'binding_id', 'install_id', 'plan_signature', 'operation_signature', 'grant_id', 'approved_revision', 'approved_signature', 'permission_digest', 'instance_id', 'source', 'actor_id', 'created_at', 'signature']) &&
    v.schema_version === 'local-skill-install-runtime-binding/v1' && text(v.binding_id) && /^sab-[a-f0-9]{64}$/.test(v.binding_id) &&
    text(v.install_id) && /^sin-[a-f0-9]{64}$/.test(v.install_id) && sig(v.plan_signature) && sig(v.operation_signature) &&
    text(v.grant_id) && v.grant_id.length <= 256 && revision(v.approved_revision) && sig(v.approved_signature) && digest(v.permission_digest) &&
    text(v.instance_id) && /^hi-[a-f0-9]{32}$/.test(v.instance_id) && isImportPermissionSource(v.source) && text(v.actor_id) &&
    v.actor_id.length <= 128 && text(v.created_at) && Number.isFinite(Date.parse(v.created_at)) && sig(v.signature);
}
export function isSkillRuntimeReadiness(v: unknown, id?: string, grantId?: string): v is SkillRuntimeReadiness {
  if (!object(v) || !exact(v, ['schema_version', 'install_id', 'grant', 'state_revision', 'status', 'binding']) ||
    v.schema_version !== 'local-skill-install-runtime-readiness/v1' || !text(v.install_id) || !/^sin-[a-f0-9]{64}$/.test(v.install_id) ||
    (id !== undefined && v.install_id !== id) || !revision(v.state_revision) || !object(v.grant) ||
    !['not_prepared', 'incomplete', 'prepared', 'no_tools'].includes(String(v.status))) return false;
  const g = v.grant;
  if (!text(g.grant_id) || (grantId !== undefined && g.grant_id !== grantId) || !sig(g.signature) || g.status !== 'approved' ||
    !text(g.admission_id) || !/^adm-si-[a-f0-9]{64}$/.test(g.admission_id) || g.platform !== 'hermes' || !object(g.subject) ||
    g.subject.type !== 'agent_instance' || !text(g.subject.id) || !/^hri-[a-f0-9]{32}$/.test(g.subject.id) ||
    !Array.isArray(g.facts) || !g.facts.every((f: unknown) => object(f) && text(f.fact_id) && text(f.domain) && text(f.action) &&
      ['allow', 'deny'].includes(String(f.effect)) && object(f.resource) && text(f.resource.value) && (f.conditions == null || object(f.conditions))) ||
    (g.expires_at != null && (!text(g.expires_at) || !Number.isFinite(Date.parse(g.expires_at))))) return false;
  if (v.binding === null) return v.status === 'not_prepared' || v.status === 'no_tools';
  if (!isSkillRuntimeBinding(v.binding) || v.status === 'not_prepared') return false;
  const b = v.binding;
  return b.install_id === v.install_id && b.grant_id === g.grant_id && b.approved_signature === g.signature &&
    b.instance_id.replace(/^hi-/, 'hri-') === g.subject.id &&
    (v.status === 'prepared' ? v.state_revision === b.approved_revision + 1 : v.status === 'incomplete' ? v.state_revision === b.approved_revision : [b.approved_revision, b.approved_revision + 1].includes(v.state_revision));
}
export function matchesInstalledReadiness(r: SkillRuntimeReadiness, v: SkillInstallView): boolean {
  const p = v.plan, b = r.binding;
  return v.status === 'installed_unverified' && !!v.operation && r.install_id === v.install_id && r.grant.grant_id === p.grant_id &&
    r.grant.signature === p.grant_signature && r.grant.subject.id === p.instance_id.replace(/^hi-/, 'hri-') &&
    (b ? b.plan_signature === p.signature && b.operation_signature === v.operation.signature && b.approved_revision === p.grant_revision &&
      b.permission_digest === p.grant_permission_digest && b.source.import_id === p.source.import_id && b.source.artifact_digest === p.source.artifact_digest && b.source.analysis_sha256 === p.source.analysis_sha256
      : r.state_revision === p.grant_revision);
}
export function isSkillActivated(v: unknown, id: string, req: SkillActivateRequest): v is SkillActivated {
  return object(v) && exact(v, ['schema_version', 'binding', 'grant_id', 'state_revision', 'runtime_verified']) &&
    v.schema_version === 'local-skill-install-activated/v1' && v.runtime_verified === false && isSkillRuntimeBinding(v.binding) &&
    v.binding.install_id === id && v.binding.operation_signature === req.operation_signature && v.binding.actor_id === req.actor_id &&
    v.binding.approved_revision === req.expected_revision && v.grant_id === v.binding.grant_id && v.state_revision === req.expected_revision + 1;
}
