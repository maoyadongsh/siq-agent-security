import { isImportPermissionSource } from './importPermissions';
import { isSkillInstallationRecord } from './skillInspection';
import { isSkillInstallPlan, isSkillInstallView } from './skillInstall';
import { isSkillRemovalView } from './skillRemoval';
import type { Grant, SkillUpdateComparison, SkillUpdateCompareRequest, SkillUpdateCreated, SkillUpdatePlan, SkillUpdateStageRequest, SkillUpdateView } from './types';
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, fields: string) => { const keys = fields.split(' '); return Object.keys(v).length === keys.length && keys.every((key) => key in v); };
const text = (v: unknown, max = 128): v is string => typeof v === 'string' && !!v.trim() && v.length <= max && !/[\u0000-\u001f\u007f]/.test(v);
const hex = (v: unknown, n: number) => typeof v === 'string' && new RegExp(`^[a-f0-9]{${n}}$`).test(v);
const sig = (v: unknown) => hex(v, 128);
const id = (v: unknown, prefix: string, n = 64): v is string => typeof v === 'string' && v.startsWith(prefix) && hex(v.slice(prefix.length), n);
const rev = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
const date = (v: unknown): v is string => typeof v === 'string' && Number.isFinite(Date.parse(v));
export const sameUpdateValue = (a: unknown, b: unknown): boolean => {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => sameUpdateValue(v, b[i]));
  return object(a) && object(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => k in b && sameUpdateValue(a[k], b[k]));
};
const resource = (v: unknown) => object(v) && text(v.type) && text(v.value, 16384);
const rule = (v: unknown) => object(v) && text(v.domain) && text(v.action) && resource(v.resource) && ['allow', 'deny'].includes(String(v.effect)) && text(v.state) && (v.conditions === null || object(v.conditions));
const grant = (v: unknown): v is Grant => object(v) && text(v.grant_id, 256) && text(v.admission_id, 256) && v.platform === 'hermes' &&
  object(v.subject) && v.subject.type === 'agent_instance' && id(v.subject.id, 'hri-', 32) && sig(v.signature) &&
  Array.isArray(v.facts) && v.facts.every((f) => object(f) && text(f.fact_id, 256) && rule({ ...f, conditions: f.conditions ?? null })) && (v.expires_at === null || date(v.expires_at));
const content = (v: unknown) => v === null || (object(v) && exact(v, 'kind sha256 bytes executable') && rev(v.bytes) && v.bytes <= 8388608 && typeof v.executable === 'boolean' &&
  (v.kind === 'directory' ? v.sha256 === '' && v.bytes === 0 && !v.executable : v.kind === 'file' && hex(v.sha256, 64)));
const count = (items: unknown[], total: unknown, truncated: unknown) => rev(total) && typeof truncated === 'boolean' && items.length <= 200 &&
  (truncated ? items.length === 200 && total > 200 : total === items.length);
const settingKeys = ['default_effect', 'enforcement_mode', 'expires_at', 'hermes_toolset_allowlist', 'openclaw_tool_policy'];
export function isSkillUpdateComparison(v: unknown, installId: string, req: SkillUpdateCompareRequest): v is SkillUpdateComparison {
  if (!object(v) || !exact(v, 'schema_version record candidate_source previous_grant previous_revision candidate_grant candidate_revision checked_at comparison_basis platform_changes runtime_verified requires_confirmation content_changes content_changes_total content_changes_truncated permission_changes permission_changes_total permission_changes_truncated settings_changed') ||
    v.schema_version !== 'local-skill-update-comparison/v1' || !isSkillInstallationRecord(v.record) || v.record.install_id !== installId ||
    v.record.recorded_status !== 'installed_unverified' || v.record.operation?.signature !== req.operation_signature || !isImportPermissionSource(v.candidate_source) ||
    !grant(v.previous_grant) || !grant(v.candidate_grant) || !rev(v.previous_revision) || v.candidate_revision !== req.expected_candidate_revision ||
    v.candidate_grant.grant_id !== req.candidate_grant_id || v.previous_grant.grant_id !== v.record.plan.grant_id || v.candidate_grant.grant_id === v.previous_grant.grant_id ||
    v.candidate_grant.subject.id !== v.record.plan.instance_id.replace(/^hi-/, 'hri-') || v.previous_grant.subject.id !== v.candidate_grant.subject.id ||
    !['draft', 'pending_approval', 'approved'].includes(v.candidate_grant.status) || !['approved', 'revoked'].includes(v.previous_grant.status) ||
    !date(v.checked_at) || v.comparison_basis !== 'signed_installation_manifest' || v.platform_changes !== false || v.runtime_verified !== false || v.requires_confirmation !== true ||
    !Array.isArray(v.content_changes) || !count(v.content_changes, v.content_changes_total, v.content_changes_truncated) ||
    !Array.isArray(v.permission_changes) || !count(v.permission_changes, v.permission_changes_total, v.permission_changes_truncated) ||
    !Array.isArray(v.settings_changed) || new Set(v.settings_changed).size !== v.settings_changed.length || !v.settings_changed.every((k) => settingKeys.includes(String(k)))) return false;
  return v.content_changes.every((c) => object(c) && exact(c, 'path_display path_digest before after') && text(c.path_display, 1024) && hex(c.path_digest, 64) &&
    content(c.before) && content(c.after) && (c.before !== null || c.after !== null)) &&
    v.permission_changes.every((c) => object(c) && exact(c, 'change rule') && ['added', 'removed'].includes(String(c.change)) && rule(c.rule));
}
export function isSkillUpdatePlan(v: unknown, updateId?: string): v is SkillUpdatePlan {
  if (!object(v) || !exact(v, 'schema_version update_id request_id record candidate_source candidate_grant_id candidate_revision candidate_signature candidate_permission_digest previous_revision previous_signature binding_signature retained_install_id revoke_previous_grant actor_id created_at expires_at file_count total_bytes platform_changes runtime_verified requires_confirmation signature') ||
    v.schema_version !== 'local-skill-update-plan/v1' || !id(v.update_id, 'sup-') || (updateId !== undefined && v.update_id !== updateId) || !id(v.request_id, 'up-', 32) ||
    !isSkillInstallationRecord(v.record) || v.record.recorded_status !== 'installed_unverified' || !v.record.operation || !isImportPermissionSource(v.candidate_source) ||
    !text(v.candidate_grant_id, 256) || v.candidate_grant_id === v.record.plan.grant_id || !rev(v.candidate_revision) || !rev(v.previous_revision) ||
    !sig(v.candidate_signature) || !sig(v.previous_signature) || !hex(v.candidate_permission_digest, 64) || !(v.binding_signature === '' || sig(v.binding_signature)) ||
    typeof v.revoke_previous_grant !== 'boolean' || !text(v.actor_id) || !date(v.created_at) || !date(v.expires_at) || Date.parse(v.expires_at) - Date.parse(v.created_at) !== 300000 ||
    !rev(v.file_count) || v.file_count < 1 || v.file_count > 2000 || !rev(v.total_bytes) || v.total_bytes > 67108864 || v.platform_changes !== false || v.runtime_verified !== false || v.requires_confirmation !== true || !sig(v.signature)) return false;
  return v.revoke_previous_grant ? v.retained_install_id === '' : id(v.retained_install_id, 'sin-') && v.retained_install_id !== v.record.install_id && sig(v.binding_signature);
}
export function isSkillUpdateCreated(v: unknown, installId: string, req: SkillUpdateStageRequest): v is SkillUpdateCreated {
  if (!object(v) || !exact(v, 'schema_version plan reused') || v.schema_version !== 'local-skill-update-plan-created/v1' || typeof v.reused !== 'boolean' || !isSkillUpdatePlan(v.plan)) return false;
  const p = v.plan;
  return p.record.install_id === installId && p.record.operation?.signature === req.operation_signature && p.request_id === req.request_id &&
    p.candidate_grant_id === req.candidate_grant_id && p.candidate_revision === req.expected_candidate_revision && p.previous_revision === req.expected_previous_revision &&
    p.binding_signature === req.expected_binding_signature && p.actor_id === req.actor_id;
}
export function comparisonMatchesPlan(c: SkillUpdateComparison, p: SkillUpdatePlan): boolean {
  return sameUpdateValue(c.record, p.record) && sameUpdateValue(c.candidate_source, p.candidate_source) && c.candidate_grant.grant_id === p.candidate_grant_id &&
    c.candidate_revision === p.candidate_revision && c.candidate_grant.signature === p.candidate_signature && c.candidate_grant.status === 'approved' &&
    c.previous_revision === p.previous_revision && c.previous_grant.signature === p.previous_signature;
}
export function isSkillUpdateView(v: unknown, updateId: string): v is SkillUpdateView {
  if (!object(v) || !exact(v, 'schema_version update_id claim result removal installation status') || v.schema_version !== 'local-skill-update-view/v1' || v.update_id !== updateId || !object(v.claim)) return false;
  const c = v.claim;
  if (!exact(c, 'schema_version update_id plan replacement_plan actor_id created_at signature') || c.schema_version !== 'local-skill-update-claim/v1' || c.update_id !== updateId ||
    !isSkillUpdatePlan(c.plan, updateId) || !isSkillInstallPlan(c.replacement_plan) || c.actor_id !== c.plan.actor_id || !date(c.created_at) || !sig(c.signature) ||
    Date.parse(c.created_at) < Date.parse(c.plan.created_at) || Date.parse(c.created_at) >= Date.parse(c.plan.expires_at)) return false;
  const p = c.plan, n = c.replacement_plan;
  if (!sameUpdateValue(n.source, p.candidate_source) || n.grant_id !== p.candidate_grant_id || n.grant_revision !== p.candidate_revision || n.grant_signature !== p.candidate_signature ||
    n.grant_permission_digest !== p.candidate_permission_digest || n.actor_id !== p.actor_id || n.created_at !== p.created_at || n.expires_at !== p.expires_at ||
    n.file_count !== p.file_count || n.total_bytes !== p.total_bytes || !['instance_id', 'platform', 'directory_name', 'target_locator_digest', 'target_display'].every((key) =>
      n[key as keyof typeof n] === p.record.plan[key as keyof typeof p.record.plan])) return false;
  const removal = v.removal;
  if (removal !== null) {
    if (!isSkillRemovalView(removal, p.record.install_id) || !sameUpdateValue(removal.record, p.record)) return false;
    const rc = removal.claim;
    if (rc && (rc.actor_id !== c.actor_id || rc.grant_revision !== p.previous_revision || rc.grant_signature !== p.previous_signature || rc.binding_signature !== p.binding_signature || rc.retained_install_id !== p.retained_install_id || rc.revoke_grant !== p.revoke_previous_grant)) return false;
  }
  const op = v.installation;
  if (op !== null && (!object(op) || !isSkillInstallView({ schema_version: 'local-skill-install-view/v1', install_id: n.plan_id.replace(/^sip-/, 'sin-'), plan: n, claim_signature: op.claim_signature, status: op.status, operation: op }, n.plan_id.replace(/^sip-/, 'sin-')))) return false;
  const r = v.result;
  if (r !== null) {
    if (!object(r) || !exact(r, 'schema_version update_id claim_signature status removal_signature installation_signature actor_id recorded_at runtime_verified signature') ||
      r.schema_version !== 'local-skill-update-result/v1' || r.update_id !== updateId || r.claim_signature !== c.signature || r.actor_id !== c.actor_id || !date(r.recorded_at) ||
      Date.parse(r.recorded_at) < Date.parse(c.created_at) || r.runtime_verified !== false || !sig(r.signature) || r.status !== v.status ||
      r.removal_signature !== (removal?.result?.signature ?? '') || r.installation_signature !== (object(op) ? op.signature : '')) return false;
    if (v.status === 'updated_unverified') return removal?.status === 'removed' && object(op) && op.status === 'installed_unverified';
    return v.status === 'aborted' && (!removal || removal.status === 'removed') && (op === null || object(op) && op.status === 'rolled_back');
  }
  if (!removal) return false;
  if (v.status === 'confirmed') return removal.status === 'not_requested' && op === null;
  if (v.status === 'removing_previous') return ['revocation_pending', 'cleanup_pending'].includes(removal.status) && op === null;
  if (v.status === 'installing_candidate') return removal.status === 'removed' && op === null;
  return v.status === 'recovery_required' && removal.status === 'removed';
}
