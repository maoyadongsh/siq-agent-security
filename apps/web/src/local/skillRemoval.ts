import { isSkillInstallationRecord } from './skillInspection';
import type { SkillRemovalView, SkillRemoveRequest } from './types';
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every((k) => k in v);
const sig = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{128}$/.test(v);
const id = (v: unknown) => typeof v === 'string' && /^sin-[a-f0-9]{64}$/.test(v);
const text = (v: unknown, max = 128): v is string => typeof v === 'string' && !!v.trim() && v.length <= max;
const rev = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
const time = (v: unknown) => typeof v === 'string' && Number.isFinite(Date.parse(v));
export function isSkillRemovalView(v: unknown, installId: string): v is SkillRemovalView {
  if (!object(v) || !exact(v, ['schema_version', 'record', 'claim', 'result', 'grant', 'state_revision', 'status', 'will_revoke_grant', 'retained_install_id', 'binding_signature']) ||
    v.schema_version !== 'local-skill-install-removal-view/v1' || !isSkillInstallationRecord(v.record) || v.record.install_id !== installId ||
    v.record.recorded_status !== 'installed_unverified' || !v.record.operation || typeof v.will_revoke_grant !== 'boolean' ||
    !(v.binding_signature === '' || sig(v.binding_signature)) || !(v.retained_install_id === '' || id(v.retained_install_id)) ||
    (v.will_revoke_grant ? v.retained_install_id !== '' : !id(v.retained_install_id) || v.retained_install_id === installId || !sig(v.binding_signature))) return false;
  const record = v.record, c = v.claim;
  if (c !== null && (!object(c) || !exact(c, ['schema_version', 'install_id', 'installation_claim_signature', 'operation_signature', 'grant_id', 'grant_revision', 'grant_signature', 'binding_signature', 'retained_install_id', 'revoke_grant', 'actor_id', 'created_at', 'signature']) ||
    c.schema_version !== 'local-skill-install-removal-claim/v1' || c.install_id !== installId || c.installation_claim_signature !== record.claim_signature ||
    c.operation_signature !== record.operation?.signature || c.grant_id !== record.plan.grant_id || !rev(c.grant_revision) || !sig(c.grant_signature) ||
    c.binding_signature !== v.binding_signature || c.retained_install_id !== v.retained_install_id || c.revoke_grant !== v.will_revoke_grant || !text(c.actor_id) || !time(c.created_at) || !sig(c.signature))) return false;
  if (v.status === 'removed') {
    const r = v.result;
    return object(c) && v.grant === null && v.state_revision === null && object(r) &&
      exact(r, ['schema_version', 'install_id', 'removal_claim_signature', 'status', 'grant_id', 'grant_revision', 'grant_signature', 'grant_revoked', 'retained_install_id', 'actor_id', 'recorded_at', 'target_absent', 'signature']) &&
      r.schema_version === 'local-skill-install-removal-result/v1' && r.install_id === installId && r.removal_claim_signature === c.signature && r.status === 'removed' &&
      r.grant_id === c.grant_id && rev(r.grant_revision) && r.grant_revision >= Number(c.grant_revision) && sig(r.grant_signature) &&
      typeof r.grant_revoked === 'boolean' && (!c.revoke_grant || r.grant_revoked) && r.retained_install_id === c.retained_install_id &&
      r.actor_id === c.actor_id && time(r.recorded_at) && r.target_absent === true && sig(r.signature);
  }
  const g = v.grant;
  if (v.result !== null || !rev(v.state_revision) || !object(g) || g.grant_id !== record.plan.grant_id || !sig(g.signature) ||
    !['approved', 'revoked'].includes(String(g.status)) || g.platform !== 'hermes' || !object(g.subject) || g.subject.type !== 'agent_instance' ||
    g.subject.id !== record.plan.instance_id.replace(/^hi-/, 'hri-') || !Array.isArray(g.facts) ||
    !g.facts.every((f: unknown) => object(f) && text(f.fact_id, 256) && text(f.domain) && text(f.action) && ['allow', 'deny'].includes(String(f.effect)) &&
      object(f.resource) && text(f.resource.value, 16384) && (f.conditions == null || object(f.conditions))) || (g.expires_at != null && !time(g.expires_at))) return false;
  if (v.status === 'not_requested') return c === null;
  if (!object(c)) return false;
  if (v.status === 'revocation_pending') return c.revoke_grant === true && g.status === 'approved' && v.state_revision === c.grant_revision && g.signature === c.grant_signature;
  return v.status === 'cleanup_pending' && (!c.revoke_grant || g.status === 'revoked');
}
export function skillRemoveRequest(view: SkillRemovalView, actor: string): SkillRemoveRequest {
  if (view.status === 'removed' || !view.record.operation || view.state_revision === null) throw new Error('skill_install_incompatible_response');
  return { schema_version: 'local-skill-install-remove/v1', operation_signature: view.record.operation.signature,
    expected_grant_revision: view.claim?.grant_revision ?? view.state_revision,
    expected_binding_signature: view.claim?.binding_signature ?? view.binding_signature,
    actor_id: view.claim?.actor_id ?? actor.trim(), confirm_remove: true };
}
