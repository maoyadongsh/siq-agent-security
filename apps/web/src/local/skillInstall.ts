import type { Grant, ImportPermissionSource, SkillInstallCreated, SkillInstallPlan, SkillInstallRequest, SkillInstallView } from './types';
import { isImportPermissionSource } from './importPermissions';

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const pattern = (v: unknown, re: RegExp): v is string => typeof v === 'string' && !/[\r\n]/.test(v) && re.test(v);
const digest = (v: unknown) => pattern(v, /^[a-f0-9]{64}$/);
const signature = (v: unknown) => pattern(v, /^[a-f0-9]{128}$/);
export function installDirectoryValid(value: string): boolean {
  return pattern(value, /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/) && !/^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/.test(value);
}
export function isSkillInstallPlan(v: unknown): v is SkillInstallPlan {
  if (!object(v) || v.schema_version !== 'local-skill-install-plan/v1' ||
    !pattern(v.plan_id, /^sip-[a-f0-9]{64}$/) || !pattern(v.request_id, /^is-[a-f0-9]{32}$/) ||
    !isImportPermissionSource(v.source) || typeof v.grant_id !== 'string' || !v.grant_id || v.grant_id.length > 256 ||
    !Number.isInteger(v.grant_revision) || Number(v.grant_revision) < 0 || !signature(v.grant_signature) ||
    !digest(v.grant_permission_digest) || v.platform !== 'hermes' || !pattern(v.instance_id, /^hi-[a-f0-9]{32}$/) ||
    typeof v.directory_name !== 'string' || !installDirectoryValid(v.directory_name) || !digest(v.target_locator_digest) ||
    typeof v.target_display !== 'string' || !v.target_display || v.target_display.length > 4096 ||
    typeof v.actor_id !== 'string' || !v.actor_id.trim() || v.actor_id.length > 128 ||
    typeof v.created_at !== 'string' || typeof v.expires_at !== 'string' ||
    !Number.isInteger(v.file_count) || Number(v.file_count) < 1 || Number(v.file_count) > 2000 ||
    !Number.isInteger(v.total_bytes) || Number(v.total_bytes) < 0 || Number(v.total_bytes) > 67108864 ||
    v.installed !== false || v.runtime_verified !== false || !signature(v.signature)) return false;
  return Number.isFinite(Date.parse(v.created_at)) && Date.parse(v.expires_at) - Date.parse(v.created_at) === 300000;
}
export function isSkillInstallCreated(v: unknown, req: SkillInstallRequest): v is SkillInstallCreated {
  if (!object(v) || v.schema_version !== 'local-skill-install-plan-created/v1' || typeof v.reused !== 'boolean' || !isSkillInstallPlan(v.plan)) return false;
  const p = v.plan;
  return p.request_id === req.request_id && p.grant_id === req.grant_id && p.grant_revision === req.expected_revision &&
    p.instance_id === req.instance_id && p.directory_name === req.directory_name && p.actor_id === req.actor_id;
}
export function matchesInstallAuthority(p: SkillInstallPlan, g: Grant, source: ImportPermissionSource): boolean {
  return g.status === 'approved' && g.platform === 'hermes' && g.subject.type === 'agent_instance' &&
    g.subject.id === p.instance_id.replace(/^hi-/, 'hri-') && g.grant_id === p.grant_id &&
    g.state_revision === p.grant_revision && g.signature === p.grant_signature &&
    source.import_id === p.source.import_id && source.artifact_digest === p.source.artifact_digest && source.analysis_sha256 === p.source.analysis_sha256;
}
export function skillInstallErrorText(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  const messages: Record<string, string> = {
    skill_install_removal_pending: '此安装已开始移除，运行权限不能重新启用。请到已安装 Skill 查看并恢复原移除操作。',
    skill_install_no_tools: '此授权未允许任何可运行工具。请重新起草并确认权限后安装，不会自动增加权限。',
    skill_install_invalid: '请检查确认选项、目录名、操作者和授权信息。',
    skill_install_recovery_required: '存在无法确认归属或已被修改的内容，恢复未完成。请保留现场并核对目标目录。',
    skill_install_reserved_metadata: '候选包含保留名称 .siq-install-owner，请修正来源后重新导入。',
    skill_install_changed: '候选内容、目标或批准权限已变化，请重新打开授权并核对。',
    skill_install_conflict: '目标目录已存在，或原请求与当前目标不一致。请核对后重新准备。',
    skill_install_expired: '安装预览已失效，请重新准备。',
    skill_install_not_found: '未找到对应安装记录或预览，请核对原操作。',
    skill_install_limit: '文件或暂存数量已达上限，当前无法生成新预览。',
    skill_install_busy: '正在检查其他候选，请稍后重试。',
    skill_install_interrupted: '预览检查中断，可重试原请求确认结果。',
    skill_install_unavailable: '暂时无法处理安装操作，请检查本地服务并查询原操作结果。',
    skill_install_incompatible_response: '安装预览与当前授权不匹配，请重新打开授权。',
  };
  return messages[code] ?? '无法确认安装结果，请检查连接并查询原操作结果。';
}

export function isSkillInstallView(v: unknown, id: string): v is SkillInstallView {
  if (!object(v) || v.schema_version !== 'local-skill-install-view/v1' || !pattern(v.install_id, /^sin-[a-f0-9]{64}$/) ||
    v.install_id !== id || !isSkillInstallPlan(v.plan) || v.plan.plan_id.replace(/^sip-/, 'sin-') !== id || !signature(v.claim_signature)) return false;
  if (v.operation === null) return v.status === 'recovery_required';
  const op = v.operation;
  return object(op) && op.schema_version === 'local-skill-install-operation/v1' && op.install_id === id &&
    op.plan_id === v.plan.plan_id && op.claim_signature === v.claim_signature && op.status === v.status &&
    ['installed_unverified', 'rolled_back', 'recovery_required'].includes(String(op.status)) &&
    typeof op.actor_id === 'string' && !!op.actor_id.trim() && op.actor_id.length <= 128 &&
    typeof op.recorded_at === 'string' && Number.isFinite(Date.parse(op.recorded_at)) && op.runtime_verified === false && signature(op.signature);
}
