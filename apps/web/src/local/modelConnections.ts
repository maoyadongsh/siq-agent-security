export interface ModelConnection {
  id: string; instance_id: string; platform: 'hermes' | 'openclaw'; instance_name: string;
  role: 'configured' | 'primary' | 'fallback'; model: string; provider: string; endpoint_display: string;
  credential: 'present' | 'missing' | 'none' | 'unsupported'; state: string; can_check: boolean; fingerprint: string;
}
export interface ModelConnections {
  schema_version: 'local-model-connections/v1'; observed_at: string; items: ModelConnection[]; partial: boolean; network_requested: false;
}
export interface ModelConnectionResult {
  schema_version: 'local-model-connection-result/v1'; id: string; fingerprint: string; status: string;
  observed_at: string; expires_at: string; inference_verified: false;
}
export const modelConfigLabels: Record<string, string> = {
  configured: '已发现模型配置', missing_model: '未找到明确模型名称', missing_endpoint: '服务地址未配置或不支持',
  unsupported_config: '配置格式需在原框架核对', unsupported_protocol: '当前检查暂不支持该接口类型',
  credential_unavailable: '已有凭据暂时无法复用', unreadable_config: '配置文件暂时无法读取',
};
export const modelResultLabels: Record<string, string> = {
  listed: '服务可达，模型已列出', not_listed: '服务可达，未列出此模型', auth_failed: '认证未通过，请在原框架核对凭据',
  rate_limited: '服务限流，请稍后重试', unreachable: '暂时无法连接服务，请检查地址或服务状态',
  unsupported_response: '未取得兼容的模型列表，请在原框架验证', service_error: '服务返回异常，请稍后重试',
};
const hash = (v: unknown) => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
const id = (v: unknown) => typeof v === 'string' && /^mc-[0-9a-f]{32}$/.test(v);
const date = (v: unknown) => typeof v === 'string' && Number.isFinite(Date.parse(v));
export function isModelConnections(value: unknown): value is ModelConnections {
  if (!value || typeof value !== 'object') return false;
  const v = value as ModelConnections;
  if (v.schema_version !== 'local-model-connections/v1' || !date(v.observed_at) || typeof v.partial !== 'boolean' || v.network_requested !== false || !Array.isArray(v.items) || v.items.length > 2048) return false;
  const seen = new Set<string>();
  return v.items.every((item) => {
    if (!item || !id(item.id) || seen.has(item.id) || typeof item.instance_id !== 'string' || !/^hi-[0-9a-f]{32}$/.test(item.instance_id)
      || !['hermes', 'openclaw'].includes(item.platform) || !['configured', 'primary', 'fallback'].includes(item.role)
      || typeof item.instance_name !== 'string' || typeof item.model !== 'string' || typeof item.provider !== 'string' || typeof item.endpoint_display !== 'string'
      || !['present', 'missing', 'none', 'unsupported'].includes(item.credential) || !Object.hasOwn(modelConfigLabels, item.state)
      || typeof item.can_check !== 'boolean' || (item.can_check && item.state !== 'configured') || !hash(item.fingerprint)) return false;
    seen.add(item.id); return true;
  });
}
export function isModelConnectionResult(value: unknown, item: ModelConnection): value is ModelConnectionResult {
  if (!value || typeof value !== 'object') return false;
  const v = value as ModelConnectionResult;
  return v.schema_version === 'local-model-connection-result/v1' && v.id === item.id && v.fingerprint === item.fingerprint
    && Object.hasOwn(modelResultLabels, v.status) && date(v.observed_at) && date(v.expires_at)
    && Date.parse(v.expires_at) > Date.parse(v.observed_at) && v.inference_verified === false;
}
