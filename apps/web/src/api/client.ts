/**
 * SIQ Agent Security — 控制面 API 客户端
 *
 * 安全不变量（与 SIQ 平台一致）：**token 绝不落 localStorage / sessionStorage**。
 * - Bearer token 仅保存在模块内存（`setToken`），页面刷新即失效；
 * - 开发/演示模式通过 `X-Dev-Tenant-Id` / `X-Dev-User-Id` 请求头注入身份，
 *   由 `VITE_DEV_MODE` 开关控制，生产构建必须关闭；
 * - 401 清内存 token 并回调 `onUnauthorized`；平台嵌入由 AuthGate 重新登录。
 */

import type {
  AgentAsset,
  AgentInstance,
  AuditEvent,
  CandidateConfirmBody,
  CandidateDismissBody,
  ClassificationRunResult,
  Environment,
  Evidence,
  Finding,
  PermissionFactRow,
  PolicyRow,
  ChangeRequestRow,
  DeploymentRow,
  RuntimeBindingRow,
  OverviewStats,
  ApiEnvelope,
} from './types';

/** 控制面 API 基础地址（默认同源，由网关/开发代理转发） */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? '/api/v1';

/** 开发模式身份注入开关（生产必须为 false，禁止身份伪造头） */
const DEV_MODE: boolean = import.meta.env.VITE_DEV_MODE === 'true';

/** 请求超时（ms）：控制面不可达时快速失败，避免页面挂起 */
const REQUEST_TIMEOUT_MS = 5000;

/* ---------------------------------------------------------------------------
 * 认证状态（仅内存）
 * ------------------------------------------------------------------------- */

/**
 * Bearer token（仅内存）。调用方通过 setToken() 注入；不要持久化。
 * 刷新页面后必须重新认证——这是 SIQ 平台安全不变量，勿改为 localStorage。
 */
let authToken: string | null = null;

/** 401 回调（清 token 后通知 UI；刷新/登录重定向由调用方实现） */
let unauthorizedHandler: (() => void) | null = null;

export function setToken(token: string | null): void {
  authToken = token;
}

export function clearToken(): void {
  authToken = null;
}

/** 注册 401 回调 */
export function onUnauthorized(handler: () => void): () => void {
  unauthorizedHandler = handler;
  return () => {
    unauthorizedHandler = null;
  };
}

/* ---------------------------------------------------------------------------
 * 请求封装
 * ------------------------------------------------------------------------- */

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** 查询参数（自动 URL 编码） */
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  /** 覆盖默认超时 */
  timeoutMs?: number;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly requestId?: string;

  constructor(status: number, message: string, code?: string, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/**
 * 展示用错误描述：HTTP 状态后缀只在 message 未自带时追加，
 * 避免"请求失败（HTTP 500）（HTTP 500）"式重复（client 兜底文案已含状态）。
 * status 0（网络失败/超时）不追加——message 本身已说明原因。
 */
export function describeApiError(err: unknown, fallback = '操作失败'): string {
  if (err instanceof ApiError) {
    return err.status && !err.message.includes(`HTTP ${err.status}`)
      ? `${err.message}（HTTP ${err.status}）`
      : err.message;
  }
  return fallback;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const base = API_BASE.replace(/\/+$/, '');
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  // 相对 base（如 /api/v1，经 vite 同源代理）时 new URL 无 base 会抛 TypeError，
  // 必须以页面 origin 为基准解析（绝对 base 时 URL 自身生效，origin 被忽略）。
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8600';
  const url = new URL(`${base}${normalizedPath}`, origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

/**
 * 通用请求。返回信封 data（兼容裸数据响应，见 types.ts ApiEnvelope 说明）。
 */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? REQUEST_TIMEOUT_MS,
  );

  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  // Bearer token：仅内存注入（见文件头安全不变量）
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  // 开发模式身份注入（仅本地联调；生产构建 VITE_DEV_MODE=false）。
  // 后端缺省角色仅 tenant_admin（无 agent:read 等权限点），故未配置
  // VITE_DEV_ROLES 时默认注入覆盖控制台全部视图所需的角色组合。
  if (DEV_MODE) {
    const tenantId = import.meta.env.VITE_DEV_TENANT_ID;
    const userId = import.meta.env.VITE_DEV_USER_ID;
    if (tenantId) headers['X-Dev-Tenant-Id'] = tenantId;
    if (userId) headers['X-Dev-User-Id'] = userId;
    const roles =
      import.meta.env.VITE_DEV_ROLES ?? 'tenant_admin,security_admin,agent_owner,auditor';
    headers['X-Dev-Roles'] = roles;
  }

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
      credentials: 'omit',
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, `请求超时（${timeout}ms）: ${path}`);
    }
    // 网络层失败（后端未启动 / CORS 等）
    throw new ApiError(0, `无法连接控制面 API（${API_BASE}）: ${path}`);
  } finally {
    clearTimeout(timeout);
  }

  if (response.status === 401) {
    // 401：清内存 token 并通知已注册处理器（无自动刷新）
    clearToken();
    unauthorizedHandler?.();
    throw new ApiError(401, '未授权（401）：会话过期或凭据无效');
  }

  if (response.status === 204) {
    return undefined as T;
  }

  // 信封解包：{ ok, data } 与裸数据两种形态兼容
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const envelope = body as ApiEnvelope<never> | null;
    throw new ApiError(
      response.status,
      envelope?.error?.message ?? `请求失败（HTTP ${response.status}）`,
      envelope?.error?.code,
      envelope?.request_id,
    );
  }

  const unwrapped = body as ApiEnvelope<T>;
  if (unwrapped && typeof unwrapped === 'object' && 'ok' in unwrapped) {
    if (!unwrapped.ok) {
      throw new ApiError(
        response.status,
        unwrapped.error?.message ?? '业务错误',
        unwrapped.error?.code,
        unwrapped.request_id,
      );
    }
    return unwrapped.data as T;
  }
  return body as T;
}

/** GET 快捷方法 */
export function get<T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
  return request<T>(path, { ...options, method: 'GET' });
}

/** POST 快捷方法（有 body 时自动 JSON 序列化） */
export function post<T>(
  path: string,
  body?: unknown,
  options: Omit<RequestOptions, 'method' | 'body'> = {},
): Promise<T> {
  return request<T>(path, { ...options, method: 'POST', body });
}

/* ---------------------------------------------------------------------------
 * 控制面端点（路径与字段对齐 apps/control-api/app/routers/ 下的实现）
 * ------------------------------------------------------------------------- */

export const api = {
  /** 总览统计（真实端点） */
  overview: () => get<OverviewStats>('/overview'),
  /** 智能体资产列表（confirmed|managed|stale|retired） */
  listAgents: () => get<AgentAsset[]>('/agents'),
  /** 智能体资产详情 */
  getAgent: (agentId: string) => get<AgentAsset>(`/agents/${encodeURIComponent(agentId)}`),
  /** 资产关联证据 */
  getAgentEvidence: (agentId: string) =>
    get<Evidence[]>(`/agents/${encodeURIComponent(agentId)}/evidence`),
  /** 资产运行时实例 */
  getAgentInstances: (agentId: string) =>
    get<AgentInstance[]>(`/agents/${encodeURIComponent(agentId)}/instances`),
  /** 发现候选列表（candidate|needs_review） */
  listCandidates: () => get<AgentAsset[]>('/candidates'),
  /** 确认候选为纳管资产（role / system_id / owner 可选） */
  confirmCandidate: (agentId: string, body: CandidateConfirmBody = {}) =>
    post<AgentAsset>(`/candidates/${encodeURIComponent(agentId)}/confirm`, body),
  /** 驳回候选（reason 必填） */
  dismissCandidate: (agentId: string, body: CandidateDismissBody) =>
    post<AgentAsset>(`/candidates/${encodeURIComponent(agentId)}/dismiss`, body),
  /** 触发候选分类（永不自动纳管；低置信 → needs_review） */
  classifyCandidate: (agentId: string) =>
    post<ClassificationRunResult>(`/candidates/${encodeURIComponent(agentId)}/classify`, {}),
  /** 权限视图（真实端点：authority/domain/state/subject_id 过滤） */
  listPermissions: (query: RequestOptions['query'] = {}) => get<PermissionFactRow[]>('/permissions', { query }),
  /** 拉取真实 OpenShell 有效策略入 PermissionFacts（fail-closed：网关不可达 502） */
  syncOpenShell: (environmentId: string) =>
    post<{ backend_targets: number; targets: number; ignored_unbound_targets: number; facts: number }>(
      '/permissions/sync-openshell',
      {},
      { query: { environment_id: environmentId } },
    ),
  /** 智能扫描（用户一键发现）：标准安全范围一次下发（hermes/openclaw/docker） */
  smartScan: (environmentId: string) =>
    post<{ tasks: { task_id: string; connector: string }[]; note: string }>(
      '/scans/smart',
      {},
      { query: { environment_id: environmentId } },
    ),
  /** 漂移检测（§13.3）：期望状态 vs 执行端实际状态 → Finding */
  checkDrift: () =>
    post<{
      drift_results: { deployment_id: string; severity: string; kind?: string; summary: string }[];
      created: number;
      updated: number;
    }>('/permissions/check-drift', {}),
  /** agent 的 Desired Policy 列表 */
  getAgentPolicies: (assetId: string) =>
    get<{ id: string; name: string; enforcement_mode: string; version: number; status: string; unsupported_by_backend: string[] }[]>(
      `/agents/${encodeURIComponent(assetId)}/policies`,
    ),
  /** agent 管控状态（诚实边界：enforced / declared_only） */
  getAgentEnforcement: (assetId: string) =>
    get<{
      agent_id: string;
      enforce_status: 'enforced' | 'declared_only';
      policy_count: number;
      effective_deployments: { id: string; policy_id: string; target: string; status: string }[];
      all_deployments: { id: string; policy_id: string; target: string; status: string }[];
    }>(`/agents/${encodeURIComponent(assetId)}/enforcement`),
  /** declared vs effective 权限 Diff（§12.4） */
  permissionsDiff: (subjectId: string) =>
    get<{
      subject_id: string;
      declared_count: number;
      effective_count: number;
      declared_not_effective: { domain: string; action: string; resource: string; detail: string }[];
      effective_not_declared: { domain: string; action: string; resource: string; detail: string }[];
      consistent: { domain: string; action: string; resource: string; detail: string }[];
    }>('/permissions/diff', { query: { subject_id: subjectId } }),
  /** 策略中心 */
  listPolicies: (query: RequestOptions['query'] = {}) => get<PolicyRow[]>('/policies', { query }),
  createPolicy: (body: Record<string, unknown>) => post<PolicyRow>('/policies', body),
  /** 变更中心 */
  listChangeRequests: (query: RequestOptions['query'] = {}) => get<ChangeRequestRow[]>('/change-requests', { query }),
  createChangeRequest: (policyId: string) =>
    post<ChangeRequestRow>('/change-requests', {
      policy_id: policyId,
      idempotency_key: `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    }),
  approveChangeRequest: (id: string) => post<ChangeRequestRow>(`/change-requests/${id}/approve`, {}),
  rejectChangeRequest: (id: string) => post<ChangeRequestRow>(`/change-requests/${id}/reject`, {}),
  listDeployments: (query: RequestOptions['query'] = {}) => get<DeploymentRow[]>('/deployments', { query }),
  createDeployment: (changeRequestId: string, environmentId: string, bindingId: string) =>
    post<DeploymentRow>('/deployments', {
      change_request_id: changeRequestId,
      environment_id: environmentId,
      binding_id: bindingId,
    }),
  /** 运行时绑定管理 */
  listRuntimeBindings: (query: RequestOptions['query'] = {}) =>
    get<RuntimeBindingRow[]>('/runtime-bindings', { query }),
  createRuntimeBinding: (body: {
    environment_id: string;
    agent_instance_id: string;
    backend: string;
    backend_target_id: string;
    attestation?: Record<string, unknown>;
  }) => post<RuntimeBindingRow>('/runtime-bindings', body),
  revokeRuntimeBinding: (bindingId: string, reason: string) =>
    post<RuntimeBindingRow>(`/runtime-bindings/${bindingId}/revoke`, { reason }),
  /** 风险中心（可按 severity / status_filter / asset_id 过滤） */
  listFindings: (query: RequestOptions['query'] = {}) => get<Finding[]>('/findings', { query }),
  /** 确认风险（状态 open → acknowledged，绑定 owner） */
  acknowledgeFinding: (findingId: string) =>
    post<Finding>(`/findings/${encodeURIComponent(findingId)}/acknowledge`, {}),
  /** 解决风险（回链修复证据，不可逆） */
  resolveFinding: (findingId: string, evidenceRef: string) =>
    post<Finding>(`/findings/${encodeURIComponent(findingId)}/resolve`, { evidence_ref: evidenceRef }),
  /** 环境与 Connector */
  listEnvironments: () => get<Environment[]>('/environments'),
  /** 审计事件（actor/action/resource_type 过滤 + 游标分页） */
  listAuditEvents: (query: RequestOptions['query'] = {}) => get<AuditEvent[]>('/audit-events', { query }),
};
