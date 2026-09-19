import type { SkillInstallView, SkillRuntimeReadiness } from './types';
export interface SkillSessionContext {
  schema_version: 'skill-execution-context/v1'; context_id: string; issuer_id: 'local-admin';
  subject: { platform: string; instance_id: string; agent_id: string; session_id: string; task_id?: string };
  skill: { skill_id: string; content_hash: string; version?: string };
  install: { install_id: string; claim_signature: string };
  authority: { grant_id: string; grant_digest: string };
  evidence_level: 'controlled_session' | 'controlled_task'; issued_at: string; expires_at: string;
  signing_schema: 'local_canonical/v1'; signature: string;
}
export interface SkillContextManagement {
  schema_version: 'local-skill-context-management/v1'; install_id: string; instance_id: string;
  sessions: { session_id: string; expires_at: string }[];
  contexts: { context: SkillSessionContext; revoked: boolean }[];
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => k in v);
const text = (v: unknown, max = 256): v is string => typeof v === 'string' && v.length > 0 && v.length <= max && v.trim() === v && !/[\u0000-\u001f\u007f]/.test(v);
const hex = (v: unknown, n: number) => typeof v === 'string' && new RegExp(`^[a-f0-9]{${n}}$`).test(v);
const date = (v: unknown): v is string => text(v) && Number.isFinite(Date.parse(v));
export function isInstalledContext(v: unknown, view: SkillInstallView, ready: SkillRuntimeReadiness): v is SkillSessionContext {
  if (!object(v) || !exact(v, ['schema_version','context_id','issuer_id','subject','skill','install','authority','evidence_level','issued_at','expires_at','signing_schema','signature']) ||
    v.schema_version !== 'skill-execution-context/v1' || v.issuer_id !== 'local-admin' || v.signing_schema !== 'local_canonical/v1' ||
    !text(v.context_id) || !/^sec-[a-f0-9]{32}$/.test(v.context_id) || !hex(v.signature,128) || !date(v.issued_at) || !date(v.expires_at) || Date.parse(v.expires_at) <= Date.parse(v.issued_at)) return false;
  const s=v.subject, i=v.install, a=v.authority, k=v.skill;
  if (!object(s) || !object(i) || !object(a) || !object(k)) return false;
  return exact(s, ['platform','instance_id','agent_id','session_id', ...(s.task_id === undefined ? [] : ['task_id'])]) &&
    s.platform === view.plan.platform && s.instance_id === view.plan.instance_id && s.agent_id === ready.grant.subject.id && text(s.session_id) &&
    (v.evidence_level === 'controlled_session' ? s.task_id === undefined : v.evidence_level === 'controlled_task' && text(s.task_id)) &&
    exact(i,['install_id','claim_signature']) && i.install_id === view.install_id && i.claim_signature === view.claim_signature && hex(i.claim_signature,128) &&
    exact(a,['grant_id','grant_digest']) && a.grant_id === view.plan.grant_id && hex(a.grant_digest,64) &&
    exact(k,['skill_id','content_hash', ...(k.version === undefined ? [] : ['version'])]) && text(k.skill_id,128) && hex(k.content_hash,64) &&
    k.skill_id === ready.grant.skill?.skill_id && k.content_hash === ready.grant.skill?.content_hash && k.version === ready.grant.skill?.version;
}
export function isSkillContextManagement(v: unknown, view: SkillInstallView, ready: SkillRuntimeReadiness): v is SkillContextManagement {
  if (!object(v) || !exact(v,['schema_version','install_id','instance_id','sessions','contexts']) || v.schema_version !== 'local-skill-context-management/v1' ||
    v.install_id !== view.install_id || v.instance_id !== view.plan.instance_id || !Array.isArray(v.sessions) || v.sessions.length > 64 || !Array.isArray(v.contexts) || v.contexts.length > 64) return false;
  const sessions = new Set<string>(), contexts = new Set<string>();
  return v.sessions.every(s => {
    if (!object(s) || !exact(s,['session_id','expires_at']) || !text(s.session_id) || !date(s.expires_at) || sessions.has(s.session_id)) return false;
    sessions.add(s.session_id); return true;
  }) && v.contexts.every(r => {
    if (!object(r) || !exact(r,['context','revoked']) || typeof r.revoked !== 'boolean' || !isInstalledContext(r.context,view,ready) || contexts.has(r.context.context_id)) return false;
    contexts.add(r.context.context_id); return true;
  });
}
export function isContextRevocation(v: unknown, id: string): boolean {
  return object(v) && exact(v,['schema_version','context_id','issuer_id','revoked_at','signing_schema','signature']) &&
    v.schema_version === 'skill-execution-context-revocation/v1' && v.context_id === id && v.issuer_id === 'local-admin' &&
    v.signing_schema === 'local_canonical/v1' && date(v.revoked_at) && hex(v.signature,128);
}
