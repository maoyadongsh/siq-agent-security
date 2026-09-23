import { get } from './client';

export const accessKeys = ['workspace', 'overview', 'agents', 'permissions', 'findings', 'policies', 'changes', 'runtime_bindings', 'environments', 'audit', 'settings'] as const;
export const actionKeys = ['confirm_assets', 'manage_environment', 'enroll_devices', 'manage_policy', 'propose_change', 'approve_change'] as const;
export type AccessKey = typeof accessKeys[number];
export interface ConsoleContext {
  schema_version: 'console-context/v1'; evaluated_at: string;
  tenant: { id: string; name: string | null }; actor: { id: string; type: 'user' | 'service' };
  authentication: 'development_headers' | 'verified_token';
  roles: { code: string; label: string; description: string }[]; custom_role_count: number;
  access: Record<AccessKey, boolean>; actions: Record<typeof actionKeys[number], boolean>;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: readonly string[]) => Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const text = (v: unknown, max = 256): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
export function isConsoleContext(v: unknown): v is ConsoleContext {
  return object(v) && exact(v, ['schema_version', 'evaluated_at', 'tenant', 'actor', 'authentication', 'roles', 'custom_role_count', 'access', 'actions']) && v.schema_version === 'console-context/v1' && text(v.evaluated_at) && v.evaluated_at.endsWith('Z') && Number.isFinite(Date.parse(v.evaluated_at))
    && object(v.tenant) && exact(v.tenant, ['id', 'name']) && text(v.tenant.id) && (v.tenant.name === null || typeof v.tenant.name === 'string' && v.tenant.name.length <= 128)
    && object(v.actor) && exact(v.actor, ['id', 'type']) && text(v.actor.id) && ['user', 'service'].includes(String(v.actor.type))
    && ['development_headers', 'verified_token'].includes(String(v.authentication))
    && Array.isArray(v.roles) && v.roles.length <= 8 && v.roles.every(r => object(r) && exact(r, ['code', 'label', 'description']) && text(r.code) && text(r.label) && typeof r.description === 'string' && r.description.length <= 256)
    && new Set(v.roles.map(r => r.code)).size === v.roles.length
    && typeof v.custom_role_count === 'number' && Number.isSafeInteger(v.custom_role_count) && v.custom_role_count >= 0
    && object(v.access) && exact(v.access, accessKeys) && accessKeys.every(key => typeof (v.access as Record<string, unknown>)[key] === 'boolean')
    && v.access.workspace === true && v.access.settings === true
    && object(v.actions) && exact(v.actions, actionKeys) && actionKeys.every(key => typeof (v.actions as Record<string, unknown>)[key] === 'boolean');
}
export async function getConsoleContext() {
  const value = await get<unknown>('/console-context');
  if (!isConsoleContext(value)) throw new Error('身份与权限响应无法核对');
  return value;
}
export function routeAccessKey(path: string): AccessKey | undefined {
  const section = path.split('?')[0].split('/')[1] || 'workspace';
  const key = section === 'runtime-bindings' ? 'runtime_bindings' : section;
  return accessKeys.includes(key as AccessKey) ? key as AccessKey : undefined;
}
export function canVisit(context: ConsoleContext | undefined, path: string): boolean {
  const key = routeAccessKey(path);
  return key === 'workspace' || key === 'settings' || !!context && !!key && context.access[key];
}
