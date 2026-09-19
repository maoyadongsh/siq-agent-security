import { isSkillInstallView, skillVersionMatches } from './skillInstall';
import type { SkillInstallationCatalog, SkillInstallationInspection, SkillInstallationRecord } from './types';
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every((k) => k in v);
const installID = (v: unknown): v is string => typeof v === 'string' && /^sin-[a-f0-9]{64}$/.test(v);
const time = (v: unknown) => typeof v === 'string' && Number.isFinite(Date.parse(v));
export function isSkillInstallationRecord(v: unknown): v is SkillInstallationRecord {
  return object(v) && exact(v, ['schema_version', 'install_id', 'plan', 'claim_signature', 'recorded_status', 'operation']) &&
    ['local-skill-install-record/v1', 'local-skill-install-record/v2'].includes(String(v.schema_version)) && installID(v.install_id) &&
    isSkillInstallView({ schema_version: String(v.schema_version).replace('local-skill-install-record/', 'local-skill-install-view/'), install_id: v.install_id, plan: v.plan,
      claim_signature: v.claim_signature, status: v.recorded_status, operation: v.operation }, v.install_id);
}
export function isSkillInstallationCatalog(v: unknown): v is SkillInstallationCatalog {
  return object(v) && exact(v, ['schema_version', 'checked_at', 'platform_changes', 'items', 'issues']) &&
    ['local-skill-install-catalog/v1', 'local-skill-install-catalog/v2'].includes(String(v.schema_version)) && v.platform_changes === false && time(v.checked_at) &&
    Array.isArray(v.items) && v.items.length <= 64 && v.items.every((item) => isSkillInstallationRecord(item) && (v.schema_version === 'local-skill-install-catalog/v2' || item.schema_version === 'local-skill-install-record/v1')) &&
    new Set(v.items.map((r) => r.install_id)).size === v.items.length && Array.isArray(v.issues) && v.issues.length <= 256 &&
    v.issues.every((i: unknown) => object(i) && exact(i, ['install_id', 'code']) && i.code === 'record_unavailable' && (i.install_id === null || installID(i.install_id)));
}
export function isSkillInstallationInspection(v: unknown, id: string): v is SkillInstallationInspection {
  if (!object(v) || !exact(v, ['schema_version', 'record', 'checked_at', 'platform_changes', 'target_state', 'comparison_complete', 'changes', 'changes_total', 'changes_truncated', 'issue_code']) ||
    !isSkillInstallationRecord(v.record) || !skillVersionMatches(v.schema_version, 'local-skill-install-inspection', v.record.schema_version, 'local-skill-install-record') || v.record.install_id !== id ||
    !time(v.checked_at) || v.platform_changes !== false || !['matched', 'changed', 'missing', 'unavailable'].includes(String(v.target_state)) ||
    typeof v.comparison_complete !== 'boolean' || !Array.isArray(v.changes) || v.changes.length > 200 ||
    !Number.isSafeInteger(v.changes_total) || Number(v.changes_total) < v.changes.length || typeof v.changes_truncated !== 'boolean' ||
    v.changes_truncated !== (Number(v.changes_total) > v.changes.length)) return false;
  if (!v.changes.every((c: unknown) => object(c) && exact(c, ['path_display', 'path_digest', 'kind', 'change']) &&
    typeof c.path_display === 'string' && !!c.path_display && [...c.path_display].length <= 1024 && !/[\x00-\x1f\x7f]/.test(c.path_display) &&
    typeof c.path_digest === 'string' && /^[a-f0-9]{64}$/.test(c.path_digest) && ['file', 'directory', 'other'].includes(String(c.kind)) &&
    ['added', 'modified', 'removed', 'type_changed', 'ownership_changed'].includes(String(c.change)))) return false;
  if (v.target_state === 'unavailable') return !v.comparison_complete && ['target_unavailable', 'comparison_budget_exceeded'].includes(String(v.issue_code));
  return v.comparison_complete && v.issue_code === null && (v.target_state === 'matched' ? v.changes_total === 0 : Number(v.changes_total) > 0);
}
