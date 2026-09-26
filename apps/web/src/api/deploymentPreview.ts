import { ApiError, post } from './client';
import type { DeploymentRow } from './types';

export interface DeploymentSelection { change_request_id: string; environment_id: string; binding_id: string }
export interface DeploymentPreview {
  schema_version: 'deployment-preview/v1'; change_id: string; policy_id: string; policy_name: string; policy_version: number;
  enforcement_mode: 'audit_only' | 'warn' | 'block'; environment_id: string; environment_name: string; binding_id: string;
  target: string; backend: 'fake' | 'openshell-cli'; action: 'development_task' | 'dynamic_update'; base_revision: string | null; preview_digest: string;
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max = 128): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;
export function parseDeploymentPreview(v: unknown, selection: DeploymentSelection): DeploymentPreview {
  const keys = ['schema_version', 'change_id', 'policy_id', 'policy_name', 'policy_version', 'enforcement_mode', 'environment_id', 'environment_name', 'binding_id', 'target', 'backend', 'action', 'base_revision', 'preview_digest'];
  if (!object(v) || Object.keys(v).length !== keys.length || !keys.every(k => k in v) || v.schema_version !== 'deployment-preview/v1' || v.change_id !== selection.change_request_id || v.environment_id !== selection.environment_id || v.binding_id !== selection.binding_id || !text(v.policy_id, 64) || !text(v.policy_name) || !Number.isInteger(v.policy_version) || (v.policy_version as number) < 1 || !text(v.environment_name) || !text(v.target) || (typeof v.enforcement_mode !== 'string' || !['audit_only', 'warn', 'block'].includes(v.enforcement_mode)) || !text(v.preview_digest, 64) || !/^[a-f0-9]{64}$/.test(v.preview_digest) || !(v.backend === 'fake' && v.action === 'development_task' && v.base_revision === null || v.backend === 'openshell-cli' && v.action === 'dynamic_update' && text(v.base_revision))) throw new Error('部署预览内容不完整或目标不匹配');
  return v as unknown as DeploymentPreview;
}
export async function readDeploymentPreview(selection: DeploymentSelection) {
  return parseDeploymentPreview(await post<unknown>('/deployment-preview', { schema_version: 'deployment-preview-request/v1', ...selection }, { timeoutMs: 60000 }), selection);
}
export function submitDeploymentPreview(selection: DeploymentSelection, value: DeploymentPreview) {
  return post<DeploymentRow>('/deployment-preview/submit', { schema_version: 'deployment-preview-submit/v1', ...selection, preview_digest: value.preview_digest }, { timeoutMs: 60000 });
}
export function deploymentPreviewError(error: unknown) {
  if (!(error instanceof ApiError)) return '暂时无法读取部署预览，请重试。';
  if (error.status === 403) return '当前账号缺少策略管理、策略读取或环境读取权限，请联系组织管理员。';
  if (error.status === 404) return '所选变更、环境或绑定不存在，或不属于当前组织。请返回重新选择。';
  const detail = error.code;
  const reasons: Record<string, string> = {
    deployment_preview_changed: '策略、目标或执行端状态已变化，请重新预览后再确认。',
    deployment_submission_exists: '此变更已有部署请求，请查看原部署记录，不要重复提交。',
    deployment_submission_key_conflict: '请求标识与原提交内容不一致，请查看已有部署记录。',
    change_not_approved: '此变更当前不可部署，请先核对审批或已有部署结果。',
    environment_not_in_enforce_mode: '所选环境尚未启用策略执行，请选择执行环境。',
    binding_revoked: '所选运行时绑定已停用，请重新选择有效绑定。',
    binding_environment_mismatch: '运行时绑定不属于所选环境，请重新选择。',
    binding_backend_mismatch: '登记绑定的后端与当前执行后端不一致，请先核对运行时接入配置。',
    binding_not_in_policy_selector: '所选运行时不在本策略的适用范围内，请选择匹配的目标。',
    selector_unknown_agent_id: '策略中的适用对象尚未确认，请先核对资产与运行时登记。',
    asset_under_quarantine: '目标资产当前处于隔离状态，不能部署。',
    enforcement_backend_disabled: '当前尚未启用部署后端，请先完成执行端接入。',
    deployment_target_identity_unconfirmed: '尚不能稳定确认执行网关身份，请配置明确的网关地址后重新预览。',
    deployment_preview_content_unavailable: '预览名称或目标包含不能直接展示的内容，请先核对配置。',
    openshell_preflight_failed: '暂时无法完成 OpenShell 检查，请核对网关连接后重试。',
    static_generation_unavailable: '此变更需要重建运行环境，当前部署入口仅支持动态更新。',
    compile_rejected: '所选后端不支持部分策略配置，请修正策略后重新申请。',
    compile_invalid: '策略未通过部署校验，请修正策略后重新申请。',
    capability_unsupported: '当前后端不支持此保护模式，请核对策略与后端能力。',
  };
  return (detail ? reasons[detail] : undefined) ?? '部署前置检查未通过，请核对目标配置后重试。';
}
