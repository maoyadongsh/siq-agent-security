/**
 * AgentShield 本地 API 客户端。
 * Bearer token 只留在模块闭包里，不进 React state、不写 localStorage。
 */
import type {
  Admission,
  AdapterResult,
  Grant,
  InventoryReport,
  PlatformInfo,
  Receipt,
  Status,
  UiBoot,
} from './types';

export type { Admission, AdapterResult, Grant, InventoryReport, PlatformInfo, Receipt, Status, UiBoot };

let token = '';

export class LocalApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function boot(): Promise<UiBoot> {
  const resp = await fetch('/ui-config.json', { cache: 'no-store' });
  if (!resp.ok) {
    throw new LocalApiError(resp.status, `无法读取 ui-config（HTTP ${resp.status}）`);
  }
  const data = (await resp.json()) as UiBoot & { token?: string };
  token = typeof data.token === 'string' ? data.token : '';
  delete data.token;
  return data;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const resp = await fetch(path, { ...init, headers, cache: 'no-store' });
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
    const err = (parsed as { error?: string } | null)?.error;
    throw new LocalApiError(resp.status, err || `HTTP ${resp.status}`);
  }
  return parsed as T;
}

export const localApi = {
  status: () => request<Status>('/v1/status'),
  inventory: (cwd?: string) => {
    const q = cwd ? `?cwd=${encodeURIComponent(cwd)}` : '';
    return request<InventoryReport>(`/v1/inventory${q}`);
  },
  admit: (path: string, trustLevel = 'unknown') =>
    request<{ admission: Admission; skill_card: string }>('/v1/admit', {
      method: 'POST',
      body: JSON.stringify({ path, trust_level: trustLevel }),
    }),
  admissions: () => request<{ admissions: Admission[] }>('/v1/admissions'),
  admission: (id: string) =>
    request<{ admission: Admission; skill_card: string }>(`/v1/admissions/${id}`),
  grants: () => request<{ grants: Grant[] }>('/v1/grants'),
  createGrant: (body: {
    admission_id: string;
    platform: string;
    subject_id: string;
    redact_secrets?: boolean;
  }) => request<{ grant: Grant }>('/v1/grants', { method: 'POST', body: JSON.stringify(body) }),
  grantAction: (id: string, action: string, body: Record<string, unknown>) =>
    request<{ grant: Grant }>(`/v1/grants/${id}/${action}`, {
      method: 'POST',
      body: JSON.stringify(body),
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
  adapterInstall: (platform: string) =>
    request<AdapterResult>('/v1/adapter/install', {
      method: 'POST',
      body: JSON.stringify({ platform }),
    }),
  adapterUninstall: (platform: string) =>
    request<AdapterResult>('/v1/adapter/uninstall', {
      method: 'POST',
      body: JSON.stringify({ platform }),
    }),
};
