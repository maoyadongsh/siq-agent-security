/**
 * siq-agent-security 本地 API 客户端。
 * Bearer token 只留在模块闭包里，不进 React state、不写 localStorage。
 */
import type {
  Admission,
  AdapterResult,
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
} from './types';

export type {
  Admission,
  AdapterResult,
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
    if (token) headers.set('Authorization', `Bearer ${token}`);
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
