import { isSkillUpdateComparison, isSkillUpdateCreated, isSkillUpdatePlan, isSkillUpdateView } from './skillUpdate';
import type { SkillUpdateCompareRequest, SkillUpdateStageRequest, SkillUpdateCommit, SkillUpdateRecover } from './types';
import { isSkillRemovalView } from './skillRemoval';
import type { SkillRemoveRequest } from './types';
import { isSkillInstallationCatalog, isSkillInstallationInspection } from './skillInspection';
import { isSkillActivated, isSkillRuntimeReadiness } from './skillRuntime';
import type { SkillActivateRequest } from './types';
import { isSkillInstallCreated, isSkillInstallPlan, isSkillInstallView } from './skillInstall';
import { isImportPermissionResult } from "./importPermissions";
import { isSkillImportList, isSkillImportResult } from "./skillImports";
import type { RuntimeIdentity } from "./types";
/**
 * siq-agent-security 本地 API 客户端。
 * 管理会话只留在模块闭包里，不进 React state、不写 localStorage。
 */
import type {
  SkillImportRequest,
  SkillInstallRequest,
  SkillInstallApply,
  ImportPermissionRequest,
  Confirmation,
  Admission,
  AdapterResult,
  AdapterPlan,
  AdapterInstances,
  Grant,
  GrantResourceEdit,
  RuntimeCheckPlan,
  RuntimeCheckResult,
  LedgerAsset,
  LedgerAssetDetail,
  LedgerFinding,
  LedgerOverview,
  PermissionFact,
  PlatformInfo,
  Receipt,
  Status,
  UiBoot,
  DiscoveryInput,
  DiscoveryPreview,
  DiscoveryStatus,
} from './types';

export type {
  Admission,
  AdapterResult,
  AdapterPlan,
  AdapterInstances,
  Grant,
  LedgerAsset,
  LedgerAssetDetail,
  LedgerFinding,
  LedgerOverview,
  PermissionFact,
  PlatformInfo,
  Receipt,
  Status,
  UiBoot,
};

let session = '';
let sessionEpoch = 0;
let restoring: Promise<boolean> | undefined;
const expiredListeners = new Set<() => void>();

export function onSessionExpired(listener: () => void): () => void {
  expiredListeners.add(listener);
  return () => { expiredListeners.delete(listener); };
}

async function fetchLocal(path: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (init.signal?.aborted) controller.abort();
  else init.signal?.addEventListener('abort', cancel, { once: true });
  const importRequest = path === '/v1/skill-imports' || path.startsWith('/v1/skill-imports/') || path.startsWith('/v1/skill-installations/');
  const timeout = setTimeout(cancel, importRequest ? 70000 : path === '/v1/adapter/preview' ? 45000 : 8000);
  try {
    return await fetch(path, { ...init, credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
  } catch {
    throw new LocalApiError(0, '无法连接本地服务。请启动 siq-agent-security serve 后重试。');
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener('abort', cancel);
  }
}

async function readObject(resp: Response): Promise<Record<string, unknown>> {
  if (!/^application\/json(?:\s*;|$)/i.test(resp.headers.get('Content-Type') ?? '')) {
    throw new LocalApiError(502, '本地服务响应格式不正确。请检查服务版本和开发代理端口。');
  }
  try {
    const data: unknown = await resp.json();
    if (data && typeof data === 'object' && !Array.isArray(data)) return data as Record<string, unknown>;
  } catch { /* HTML fallback and malformed JSON are not a working local API. */ }
  throw new LocalApiError(502, '本地服务响应格式不正确。请检查服务版本和开发代理端口。');
}

function acceptSession(data: Record<string, unknown>): string {
  if (data.schema_version !== 'local-admin-session/v1' || data.scope !== 'admin' ||
      typeof data.session !== 'string' || !/^[0-9a-f]{64}$/.test(data.session) ||
      typeof data.expires_in !== 'number' || !Number.isInteger(data.expires_in) ||
      data.expires_in < 1 || data.expires_in > 43200) {
    throw new LocalApiError(502, '管理会话响应不兼容，请更新本地服务后重试。');
  }
  return data.session;
}

export class LocalApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function boot(): Promise<UiBoot> {
  const resp = await fetchLocal('/ui-config.json');
  if (!resp.ok) {
    throw new LocalApiError(resp.status, `无法读取 ui-config（HTTP ${resp.status}）`);
  }
  const data = await readObject(resp);
  if ('token' in data || 'session' in data) {
    throw new LocalApiError(500, 'ui-config 返回了凭据，已拒绝启动');
  }
  if (data.schema_version !== 'local-ui-config/v1' || data.product !== 'siq-agent-security' ||
      data.local_mode !== true || data.single_user !== true || typeof data.version !== 'string' ||
      !data.version || typeof data.session_recovery !== 'boolean' || typeof data.pairing_available !== 'boolean' ||
      !['block', 'warn', 'audit_only'].includes(String(data.enforcement_mode))) {
    throw new LocalApiError(502, '本地服务版本不兼容或连接到了其他服务，请更新 SIQ 服务并检查端口。');
  }
  return data as unknown as UiBoot;
}

export async function pair(code: string): Promise<void> {
  const epoch = ++sessionEpoch;
  const resp = await fetchLocal('/v1/pair', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-SIQ-Session': '1' },
    body: JSON.stringify({ code, remember: true }),
  });
  if (!resp.ok) {
    throw new LocalApiError(resp.status, resp.status === 401
      ? '配对码无效、已使用或已过期。请运行 siq-agent-security pair 获取新码。'
      : `配对失败（HTTP ${resp.status}），请检查本地服务。`);
  }
  const next = acceptSession(await readObject(resp));
  if (epoch === sessionEpoch) session = next;
}

export function restoreSession(): Promise<boolean> {
  if (restoring) return restoring;
  const epoch = sessionEpoch;
  restoring = (async () => {
    const resp = await fetchLocal('/v1/session/restore', { method: 'POST', headers: { 'X-SIQ-Session': '1' } });
    if (resp.status === 401) {
      if (epoch === sessionEpoch) session = '';
      return false;
    }
    if (!resp.ok) throw new LocalApiError(resp.status, `无法恢复管理会话（HTTP ${resp.status}）`);
    const next = acceptSession(await readObject(resp));
    if (epoch !== sessionEpoch) return false;
    session = next;
    return true;
  })().finally(() => { restoring = undefined; });
  return restoring;
}

export async function logout(): Promise<void> {
  ++sessionEpoch; // An in-flight restore must not repopulate a signed-out session.
  const result = await request<{ schema_version?: string; signed_out?: boolean }>('/v1/session/logout', { method: 'POST' });
  if (result?.schema_version !== 'local-logout/v1' || result.signed_out !== true) {
    throw new LocalApiError(502, '无法确认管理会话已退出，请检查服务后重试。');
  }
  session = '';
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (session) headers.set('Authorization', `Bearer ${session}`);
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const resp = await fetchLocal(path, { ...init, headers });
  const text = await resp.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      parsed = { error: text };
    }
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      session = '';
      ++sessionEpoch;
      expiredListeners.forEach((listener) => listener());
    }
    const err = (parsed as { error?: string } | null)?.error;
    throw new LocalApiError(resp.status, err || `HTTP ${resp.status}`);
  }
  return parsed as T;
}

export const localApi = {
  compareSkillUpdate: (id: string, body: SkillUpdateCompareRequest, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}/update-comparison`, { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillUpdateComparison(data, id, body)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  prepareSkillUpdate: (id: string, body: SkillUpdateStageRequest, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}/update-plans`, { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillUpdateCreated(data, id, body)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  skillUpdatePlan: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/update-plans/${encodeURIComponent(id)}`, { signal }).then((data) => {
    if (!isSkillUpdatePlan(data, id)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  skillUpdate: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/updates/${encodeURIComponent(id)}`, { signal }).then((data) => {
    if (!isSkillUpdateView(data, id)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  commitSkillUpdate: (body: SkillUpdateCommit, signal?: AbortSignal) => request<unknown>('/v1/skill-installations/updates', { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillUpdateView(data, body.update_id) || data.claim.plan.signature !== body.plan_signature || data.claim.actor_id !== body.actor_id) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  recoverSkillUpdate: (body: SkillUpdateRecover, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/updates/${encodeURIComponent(body.update_id)}/recover`, { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillUpdateView(data, body.update_id) || data.claim.signature !== body.claim_signature || data.claim.actor_id !== body.actor_id) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),

  skillRemoval: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}/removal`, { signal }).then((data) => {
    if (!isSkillRemovalView(data, id)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  removeSkill: (id: string, body: SkillRemoveRequest, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}/removal`, { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillRemovalView(data, id) || !data.claim || data.claim.operation_signature !== body.operation_signature ||
      data.claim.grant_revision !== body.expected_grant_revision || data.claim.binding_signature !== body.expected_binding_signature || data.claim.actor_id !== body.actor_id) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  skillInstallations: (signal?: AbortSignal) => request<unknown>('/v1/skill-installations/operations', { signal }).then((data) => {
    if (!isSkillInstallationCatalog(data)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  inspectSkillInstallation: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}/inspection`, { signal }).then((data) => {
    if (!isSkillInstallationInspection(data, id)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  skillRuntimeReadiness: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}/runtime`, { signal }).then((data) => {
    if (!isSkillRuntimeReadiness(data, id)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  skillGrantReadiness: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/grants/${encodeURIComponent(id)}/runtime`, { signal }).then((data) => {
    if (!isSkillRuntimeReadiness(data, undefined, id)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  activateSkillInstallation: (id: string, body: SkillActivateRequest, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}/activate`, { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillActivated(data, id, body)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  applySkillInstall: (body: SkillInstallApply, signal?: AbortSignal) => request<unknown>('/v1/skill-installations/apply', { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillInstallView(data, body.plan_id.replace(/^sip-/, 'sin-')) || data.plan.signature !== body.plan_signature || data.plan.actor_id !== body.actor_id) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  skillInstallation: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}`, { signal }).then((data) => {
    if (!isSkillInstallView(data, id)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  recoverSkillInstallation: (id: string, actor: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/operations/${encodeURIComponent(id)}/recover`, { method: 'POST', body: JSON.stringify({ schema_version: 'local-skill-install-recover/v1', actor_id: actor, confirm_recovery: true }), signal }).then((data) => {
    if (!isSkillInstallView(data, id) || data.status !== 'rolled_back') throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),

  createInstallPlan: (body: SkillInstallRequest, signal?: AbortSignal) => request<unknown>('/v1/skill-installations/plans', { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillInstallCreated(data, body)) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  installPlan: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-installations/plans/${encodeURIComponent(id)}`, { signal }).then((data) => {
    if (!isSkillInstallPlan(data) || data.plan_id !== id) throw new LocalApiError(502, 'skill_install_incompatible_response');
    return data;
  }),
  skillImports: (signal?: AbortSignal) => request<unknown>('/v1/skill-imports', { signal }).then((data) => {
    if (!isSkillImportList(data)) throw new LocalApiError(502, 'skill_import_incompatible_response');
    return data;
  }),
  skillImport: (id: string, signal?: AbortSignal) => request<unknown>(`/v1/skill-imports/${encodeURIComponent(id)}`, { signal }).then((data) => {
    if (!isSkillImportResult(data, id)) throw new LocalApiError(502, 'skill_import_incompatible_response');
    return data;
  }),
  prepareImportPermissions: (id: string, body: ImportPermissionRequest, signal?: AbortSignal) =>
    request<unknown>(`/v1/skill-imports/${encodeURIComponent(id)}/permissions`, { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
      if (!isImportPermissionResult(data, id, body)) throw new LocalApiError(502, 'skill_import_incompatible_response');
      return data;
    }),
  createSkillImport: (body: SkillImportRequest, signal?: AbortSignal) => request<unknown>(body.schema_version === 'local-skill-import-remote-create/v1' ? '/v1/skill-imports/remote' : '/v1/skill-imports', { method: 'POST', body: JSON.stringify(body), signal }).then((data) => {
    if (!isSkillImportResult(data, body.import_id) || data.schema_version !== (body.schema_version === 'local-skill-import-remote-create/v1' ? 'local-skill-import-result/v2' : 'local-skill-import-result/v1')) throw new LocalApiError(502, 'skill_import_incompatible_response');
    return data;
  }),
  discoveryStatus: () => request<DiscoveryStatus>('/v1/discovery'),
  discoveryPreview: (input: DiscoveryInput) => request<DiscoveryPreview>('/v1/discovery/preview', { method: 'POST', body: JSON.stringify(input) }),
  discoveryScan: (input: DiscoveryInput) => request<DiscoveryStatus>('/v1/discovery/scan', { method: 'POST', body: JSON.stringify(input) }),
  status: () => request<Status>('/v1/status'),
  assets: (cwd?: string) => {
    const q = cwd ? `?cwd=${encodeURIComponent(cwd)}` : '';
    return request<{ assets: LedgerAsset[]; overview: LedgerOverview }>(`/v1/assets${q}`);
  },
  asset: (id: string) =>
    request<LedgerAssetDetail>(`/v1/assets/${encodeURIComponent(id)}`),
  confirmAsset: (id: string, actorId: string) =>
    request<{ asset: LedgerAsset }>(`/v1/assets/${encodeURIComponent(id)}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ actor_id: actorId }),
    }),
  dismissAsset: (id: string, body: { actor_id: string; reason: string; until: string }) =>
    request<{ asset: LedgerAsset }>(`/v1/assets/${encodeURIComponent(id)}/dismiss`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  permissions: (subjectId?: string) => {
    const q = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : '';
    return request<{ facts: PermissionFact[] }>(`/v1/permissions${q}`);
  },
  findings: () => request<{ findings: LedgerFinding[] }>('/v1/findings'),
  acceptFinding: (id: string, body: { actor_id: string; reason: string; until: string }) =>
    request(`/v1/findings/${encodeURIComponent(id)}/accept`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  audit: () => request<{ events: { at: string; event: string; actor_id?: string; target?: string; note?: string }[] }>('/v1/audit'),
  admit: (path: string, trustLevel = 'unknown') =>
    request<{ admission: Admission; skill_card: string }>('/v1/admit', {
      method: 'POST',
      body: JSON.stringify({ path, trust_level: trustLevel }),
    }),
  admissions: () => request<{ admissions: Admission[] }>("/v1/admissions"),
  runtimeIdentities: () => request<{ items: RuntimeIdentity[] }>("/v1/runtime-identities"),
  createRuntimeIdentity: (instanceId: string, grantId: string, revision: number, actorId: string, ttl: number) =>
    request<{ identity: RuntimeIdentity }>("/v1/runtime-identities", { method: "POST", body: JSON.stringify({
      schema_version: "local-runtime-identity-create/v1", instance_id: instanceId, grant_id: grantId,
      expected_grant_revision: revision, actor_id: actorId, session_ttl_seconds: ttl,
    }) }),
  revokeRuntimeIdentity: (id: string, actorId: string) => request(`/v1/runtime-identities/${encodeURIComponent(id)}/revoke`, {
    method: "POST", body: JSON.stringify({ schema_version: "local-runtime-identity-revoke/v1", actor_id: actorId }),
  }),
  admission: (id: string) =>
    request<{ admission: Admission; skill_card: string }>(`/v1/admissions/${id}`),
  grants: (signal?: AbortSignal) =>
    request<{ grants: Grant[]; state_revisions?: Record<string, number> }>('/v1/grants', { signal }).then((data) => {
      const revs = data.state_revisions ?? {};
      return {
        ...data,
        grants: (data.grants ?? []).map((g) => ({
          ...g,
          state_revision: revs[g.grant_id] ?? g.state_revision,
        })),
      };
    }),
  createGrant: (body: {
    admission_id: string;
    platform: string;
    subject_id: string;
    redact_secrets?: boolean;
  }) => request<{ grant: Grant; state_revision?: number }>('/v1/grants', { method: 'POST', body: JSON.stringify(body) }),
  draftGrant: (id: string, revision: number, actor: string, requestId: string) =>
    request<{ schema_version: 'grant-draft-created/v1'; source_grant_id: string; source_revision: number; grant: Grant; state_revision: number; reused: boolean }>(`/v1/grants/${id}/draft`, {
      method: 'POST', body: JSON.stringify({ schema_version: 'grant-draft-create/v1', expected_revision: revision, actor_id: actor, request_id: requestId }),
    }),
  grantAction: (id: string, action: string, body: Record<string, unknown>) =>
    request<{
      grant?: Grant;
      challenge?: { challenge_id: string; nonce: string; grant_digest?: string; expires_at?: string };
      state_revision?: number;
      note?: string;
    }>(`/v1/grants/${id}/${action}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  setGrantExpiry: (id: string, revision: number, actorId: string, durationSeconds: number | null) =>
    request<{ grant: Grant; state_revision: number }>(`/v1/grants/${encodeURIComponent(id)}/expiry`, {
      method: 'POST',
      body: JSON.stringify({ schema_version: 'grant-expiry-edit/v1', expected_revision: revision,
        actor_id: actorId, duration_seconds: durationSeconds }),
    }),
  setGrantResources: (id: string, revision: number, actorId: string, resources: GrantResourceEdit) =>
    request<{ grant: Grant; state_revision: number }>(`/v1/grants/${encodeURIComponent(id)}/resources`, {
      method: 'POST', body: JSON.stringify({ schema_version: 'grant-resource-edit/v1',
        expected_revision: revision, actor_id: actorId, ...resources }),
    }),
  runtimeCheckPreview: (instanceId: string) => request<RuntimeCheckPlan>('/v1/runtime-checks/preview', {
    method: 'POST', body: JSON.stringify({ schema_version: 'local-runtime-check-preview/v1', instance_id: instanceId }),
  }),
  runtimeCheckStart: (plan: RuntimeCheckPlan, actorId: string) => request<RuntimeCheckResult>('/v1/runtime-checks/start', {
    method: 'POST', body: JSON.stringify({ schema_version: 'local-runtime-check-start/v1', check_id: plan.check_id,
      plan_digest: plan.plan_digest, actor_id: actorId, confirm: true }),
  }),
  runtimeCheck: (id: string) => request<RuntimeCheckResult>(`/v1/runtime-checks/${encodeURIComponent(id)}`),
  runtimeCheckLatest: (instanceId: string) => request<{ schema_version: 'local-runtime-check-list/v1'; items: RuntimeCheckResult[] }>(
    `/v1/runtime-checks?instance_id=${encodeURIComponent(instanceId)}`),
  runtimeCheckCancel: (id: string) => request<RuntimeCheckResult>(`/v1/runtime-checks/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  runtimeCheckCleanup: (id: string) => request<RuntimeCheckResult>(`/v1/runtime-checks/${encodeURIComponent(id)}/cleanup`, { method: 'POST' }),
  grant: (id: string) =>
    request<{ grant: Grant; state_revision: number }>(`/v1/grants/${id}`).then((data) => ({
      grant: { ...data.grant, state_revision: data.state_revision },
      state_revision: data.state_revision,
    })),
  confirmations: () => request<{ schema_version: 'local-confirmations/v1'; items: Confirmation[] }>('/v1/confirmations'),
  resolveConfirmation: (item: Confirmation, approve: boolean, actorId: string) =>
    request<{ receipt_id: string; action: string }>(`/v1/confirmations/${encodeURIComponent(item.action_id)}/resolve`, {
      method: 'POST', body: JSON.stringify({ schema_version: 'local-confirmation-resolve/v1',
        decision_receipt_id: item.decision_receipt_id, decision_hash: item.decision_hash,
        params_digest: item.params_digest, approve, actor_id: actorId }),
    }),
  receipts: () => request<{ receipts: Receipt[]; verified: boolean }>('/v1/receipts?since_seq=-1'),
  resolveHold: (id: string, approve: boolean, actorId: string) =>
    request(`/v1/hold/${id}`, {
      method: 'POST',
      body: JSON.stringify({ approve, actor_id: actorId }),
    }),
  putConfig: (enforcement_mode: string) =>
    request('/v1/config', {
      method: 'PUT',
      body: JSON.stringify({ enforcement_mode }),
    }),
  adapterStatus: () =>
    request<{ detected: string[]; platforms: PlatformInfo[] }>('/v1/adapter/status'),
  adapterInstances: (platform: string) => request<AdapterInstances>(`/v1/adapter/instances?platform=${encodeURIComponent(platform)}`),
  adapterPreview: (platform: string, action: 'install' | 'uninstall', instance_id?: string, native_enable = false, runtime_identity_id?: string) =>
    request<AdapterPlan>('/v1/adapter/preview', { method: 'POST', body: JSON.stringify({ platform, action, instance_id, native_enable, runtime_identity_id }) }),
  adapterApply: (plan: AdapterPlan, actor_id?: string) =>
    request<AdapterResult>(`/v1/adapter/${plan.action}`, {
      method: 'POST',
      body: JSON.stringify({ platform: plan.platform, plan_id: plan.plan_id, plan_digest: plan.plan_digest, instance_id: plan.instance_id, runtime_identity_id: plan.runtime_identity_id, actor_id }),
    }),
  adapterRecover: (platform: string, instance_id?: string) =>
    request<AdapterResult>('/v1/adapter/recover', { method: 'POST', body: JSON.stringify({ platform, instance_id }) }),
  openshellProbe: () =>
    request<{
      ok: boolean;
      tier: string;
      note?: string;
      schema_version?: string;
      dynamic_network_update?: boolean;
      revision_support?: boolean;
      doctor?: {
        source?: string;
        human_next?: string;
        cli_found?: boolean;
        identity_ok?: boolean;
        started_gateway?: boolean;
      };
    }>('/v1/openshell/probe'),
  openshellApply: (body: {
    target: string;
    network: { endpoint: string; effect?: string }[];
    expected_revision?: string;
    expect_allow?: string[];
    expect_deny?: string[];
  }) =>
    request<{
      ok?: boolean;
      passed?: boolean;
      verify_level?: string;
      error?: string;
      effective_readback?: { backend: string; revision: string; evidence_id: string };
      failures?: string[];
    }>('/v1/openshell/apply', { method: 'POST', body: JSON.stringify(body) }),
  openshellDriftCheck: () =>
    request<{ ok?: boolean; findings_written?: string[]; error?: string }>('/v1/openshell/drift-check', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  downloadExport: async () => {
    const headers = new Headers();
    if (session) headers.set('Authorization', `Bearer ${session}`);
    const resp = await fetch('/v1/export', { headers, cache: 'no-store' });
    if (!resp.ok) {
      let message = `HTTP ${resp.status}`;
      const text = await resp.text();
      try {
        const parsed = JSON.parse(text) as { error?: string };
        if (parsed.error) message = parsed.error;
      } catch {
        if (text) message = text;
      }
      throw new LocalApiError(resp.status, message);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    try {
      const a = document.createElement('a');
      a.href = url;
      a.download = 'siq-agent-security-export.json';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      URL.revokeObjectURL(url);
    }
  },
};
