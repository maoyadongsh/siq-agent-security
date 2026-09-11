import type { ImportPermissionRequest, ImportPermissionResult, ImportPermissionSource } from './types';

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
export function isImportPermissionSource(v: unknown): v is ImportPermissionSource {
  return object(v) && v.schema_version === 'local-skill-import-permission-source/v1' &&
    typeof v.import_id === 'string' && /^si-[a-f0-9]{32}$/.test(v.import_id) && hash(v.artifact_digest) && hash(v.analysis_sha256);
}
export function isImportPermissionResult(v: unknown, id: string, req: ImportPermissionRequest): v is ImportPermissionResult {
  if (!object(v) || v.schema_version !== 'local-skill-import-permission-created/v1' || v.import_id !== id ||
    v.installed !== false || typeof v.reused !== 'boolean' || !Number.isInteger(v.state_revision) || Number(v.state_revision) < 0 ||
    !isImportPermissionSource(v.source) || v.source.import_id !== id || v.source.artifact_digest !== req.artifact_digest ||
    v.source.analysis_sha256 !== req.analysis_sha256 || !object(v.grant)) return false;
  const g = v.grant;
  return typeof g.grant_id === 'string' && /^grt-si-[a-f0-9]{64}$/.test(g.grant_id) &&
    typeof g.admission_id === 'string' && /^adm-si-[a-f0-9]{64}$/.test(g.admission_id) && g.platform === 'hermes' &&
    object(g.subject) && g.subject.type === 'agent_instance' && g.subject.id === req.instance_id.replace(/^hi-/, 'hri-') &&
    ['pending_approval', 'approved', 'rejected', 'revoked'].includes(String(g.status));
}
