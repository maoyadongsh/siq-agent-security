import type { ModelConnection } from './modelConnections';
export interface ModelInferenceRecord {
  schema_version: 'local-model-inference-record/v1'; request_id: string; model_id: string; fingerprint: string;
  status: string; started_at: string; finished_at: string; expires_at: string;
  inference_verified: boolean; business_data_sent: false; service_session_only: true;
}
export const inferenceLabels: Record<string, string> = {
  running: '正在等待模型回答…', passed: '模型回答测试通过', response_mismatch: '模型已响应，但未通过测试内容或模型身份核对',
  auth_failed: '认证未通过，请在原框架核对凭据', rate_limited: '服务限流，本次未自动重试',
  unsupported_response: '服务响应与当前测试协议不兼容', service_error: '服务返回异常，本次未自动重试',
  uncertain: '未取得最终结果，服务可能已接收请求；本次未自动重试', configuration_changed: '配置或凭据已变化，本次结果已失效',
};
export function isModelInferenceRecord(value: unknown, item: ModelConnection): value is ModelInferenceRecord {
  if (!value || typeof value !== 'object') return false;
  const v = value as ModelInferenceRecord;
  return v.schema_version === 'local-model-inference-record/v1' && /^mt-[0-9a-f]{32}$/.test(v.request_id)
    && v.model_id === item.id && /^[0-9a-f]{64}$/.test(v.fingerprint) && Object.hasOwn(inferenceLabels, v.status)
    && Number.isFinite(Date.parse(v.started_at)) && v.inference_verified === (v.status === 'passed')
    && v.business_data_sent === false && v.service_session_only === true
    && (v.status === 'running' ? v.finished_at === '' && v.expires_at === ''
      : Number.isFinite(Date.parse(v.finished_at)) && Date.parse(v.expires_at) > Date.parse(v.finished_at));
}
