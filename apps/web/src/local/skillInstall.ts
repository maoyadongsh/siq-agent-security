import type { Grant, ImportPermissionSource, SkillInstallCreated, SkillInstallPlan, SkillInstallRequest, SkillInstallView, SkillInstallTargetRef, SkillInstallationTargets } from './types';
import { isImportPermissionSource } from './importPermissions';
import { grantFilesystemProfile, windowsFilesystemProfile } from './filesystemProfile';

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const pattern = (v: unknown, re: RegExp): v is string => typeof v === 'string' && !/[\r\n]/.test(v) && re.test(v);
const digest = (v: unknown) => pattern(v, /^[a-f0-9]{64}$/);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every((key) => key in v);
const signature = (v: unknown) => pattern(v, /^[a-f0-9]{128}$/);
export function installDirectoryValid(value: string): boolean {
  return pattern(value, /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/) && !/^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/.test(value);
}
export function isSkillInstallRequest(value: unknown): value is SkillInstallRequest {
  if (!object(value) || !['local-skill-install-stage-create/v1', 'local-skill-install-stage-create/v2'].includes(String(value.schema_version)) ||
    !exact(value, ['schema_version', 'request_id', 'grant_id', 'expected_revision', 'instance_id', 'directory_name', 'actor_id', ...(value.schema_version === 'local-skill-install-stage-create/v2' ? ['target_id'] : [])]) ||
    !pattern(value.request_id, /^is-[a-f0-9]{32}$/) || !pattern(value.instance_id, /^hi-[a-f0-9]{32}$/) ||
    typeof value.grant_id !== 'string' || !value.grant_id || value.grant_id.length > 256 ||
    !Number.isSafeInteger(value.expected_revision) || Number(value.expected_revision) < 0 ||
    typeof value.directory_name !== 'string' || !installDirectoryValid(value.directory_name) ||
    typeof value.actor_id !== 'string' || !value.actor_id.trim() || value.actor_id.length > 128) return false;
  return value.schema_version === 'local-skill-install-stage-create/v1' || pattern(value.target_id, /^sit-[a-f0-9]{64}$/);
}
export function isSkillInstallPlan(v: unknown): v is SkillInstallPlan {
  if (!object(v) || !['local-skill-install-plan/v1', 'local-skill-install-plan/v2'].includes(String(v.schema_version)) ||
    !exact(v, [...planFields, ...(v.schema_version === 'local-skill-install-plan/v2' ? ['target_ref'] : [])]) ||
    (v.schema_version === 'local-skill-install-plan/v2' ? v.platform !== 'workbuddy' || !isSkillInstallTargetRef(v.target_ref) : !['hermes', 'openclaw'].includes(String(v.platform))) ||
    !pattern(v.plan_id, /^sip-[a-f0-9]{64}$/) || !pattern(v.request_id, /^is-[a-f0-9]{32}$/) ||
    !isImportPermissionSource(v.source) || typeof v.grant_id !== 'string' || !v.grant_id || v.grant_id.length > 256 ||
    !Number.isInteger(v.grant_revision) || Number(v.grant_revision) < 0 || !signature(v.grant_signature) ||
    !digest(v.grant_permission_digest) || !pattern(v.instance_id, /^hi-[a-f0-9]{32}$/) ||
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
  if (!isSkillInstallRequest(req) || !object(v) || !exact(v, ['schema_version', 'plan', 'reused']) || typeof v.reused !== 'boolean' || !isSkillInstallPlan(v.plan) ||
    !skillVersionMatches(v.schema_version, 'local-skill-install-plan-created', v.plan.schema_version, 'local-skill-install-plan') ||
    !skillVersionMatches(req.schema_version, 'local-skill-install-stage-create', v.plan.schema_version, 'local-skill-install-plan')) return false;
  const p = v.plan;
  return p.request_id === req.request_id && p.grant_id === req.grant_id && p.grant_revision === req.expected_revision &&
    p.instance_id === req.instance_id && p.directory_name === req.directory_name && p.actor_id === req.actor_id &&
    (req.schema_version === 'local-skill-install-stage-create/v2' ? p.schema_version === 'local-skill-install-plan/v2' && p.target_ref.target_id === req.target_id : !('target_id' in req));
}
export function matchesInstallAuthority(p: SkillInstallPlan, g: Grant, source: ImportPermissionSource): boolean {
  return (p.schema_version !== 'local-skill-install-plan/v2' || grantFilesystemProfile(g) === windowsFilesystemProfile) && g.status === 'approved' && g.platform === p.platform && g.subject.type === 'agent_instance' &&
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
  if (!object(v) || !exact(v, ['schema_version', 'install_id', 'plan', 'claim_signature', 'status', 'operation']) || !pattern(v.install_id, /^sin-[a-f0-9]{64}$/) ||
    v.install_id !== id || !isSkillInstallPlan(v.plan) || !skillVersionMatches(v.schema_version, 'local-skill-install-view', v.plan.schema_version, 'local-skill-install-plan') || v.plan.plan_id.replace(/^sip-/, 'sin-') !== id || !signature(v.claim_signature)) return false;
  if (v.operation === null) return v.status === 'recovery_required';
  const op = v.operation;
  return object(op) && exact(op, ['schema_version', 'install_id', 'plan_id', 'claim_signature', 'status', 'actor_id', 'recorded_at', 'runtime_verified', 'signature']) && op.schema_version === 'local-skill-install-operation/v1' && op.install_id === id &&
    op.plan_id === v.plan.plan_id && op.claim_signature === v.claim_signature && op.status === v.status &&
    ['installed_unverified', 'rolled_back', 'recovery_required'].includes(String(op.status)) &&
    typeof op.actor_id === 'string' && !!op.actor_id.trim() && op.actor_id.length <= 128 &&
    typeof op.recorded_at === 'string' && Number.isFinite(Date.parse(op.recorded_at)) && op.runtime_verified === false && signature(op.signature);
}

const planFields = ['schema_version', 'plan_id', 'request_id', 'source', 'grant_id', 'grant_revision', 'grant_signature', 'grant_permission_digest', 'platform', 'instance_id', 'directory_name', 'target_locator_digest', 'target_display', 'actor_id', 'created_at', 'expires_at', 'file_count', 'total_bytes', 'installed', 'runtime_verified', 'signature'];
export function skillVersionMatches(outer: unknown, prefix: string, inner: unknown, innerPrefix: string): boolean {
  return (outer === `${prefix}/v1` && inner === `${innerPrefix}/v1`) || (outer === `${prefix}/v2` && inner === `${innerPrefix}/v2`);
}
export function isSkillInstallTargetRef(value: unknown): value is SkillInstallTargetRef {
  if (!object(value) || !exact(value, ['target_id', 'scope', 'filesystem_profile', 'root_locator_digest', 'root_identity_digest', 'config_root_identity_digest', 'existing_parent_relative_path', 'existing_parent_identity_digest']) ||
    !pattern(value.target_id, /^sit-[a-f0-9]{64}$/) || value.filesystem_profile !== windowsFilesystemProfile ||
    !['root_locator_digest', 'root_identity_digest', 'config_root_identity_digest', 'existing_parent_identity_digest'].every((key) => digest(value[key]))) return false;
  return (value.scope === 'user' && ['', 'skills'].includes(String(value.existing_parent_relative_path))) ||
    (value.scope === 'project' && ['', '.codebuddy', '.codebuddy/skills'].includes(String(value.existing_parent_relative_path)));
}
export function isSkillInstallationTargets(value: unknown, instanceId: string): value is SkillInstallationTargets {
  const display = (v: unknown) => typeof v === 'string' && v.length >= 1 && [...v].length <= 4096 && !/[\x00-\x1f\x7f]/.test(v) && !/^(?:[a-zA-Z]:[\\/]|[\\/]{2})/.test(v);
  if (!object(value) || !exact(value, ['schema_version', 'instance_id', 'targets', 'platform_changes']) || value.schema_version !== 'local-skill-install-targets/v1' ||
    value.instance_id !== instanceId || !pattern(value.instance_id, /^hi-[a-f0-9]{32}$/) || value.platform_changes !== false || !Array.isArray(value.targets) || value.targets.length > 17) return false;
  const ids = new Set<string>(); let userCount = 0, projectCount = 0;
  return value.targets.every((row) => {
    if (!object(row) || !exact(row, ['target_id', 'instance_id', 'platform', 'scope', 'root_display', 'target_display', 'filesystem_profile', 'available', 'error_code']) ||
      !pattern(row.target_id, /^sit-[a-f0-9]{64}$/) || ids.has(row.target_id) || row.instance_id !== instanceId || row.platform !== 'workbuddy' ||
      row.filesystem_profile !== windowsFilesystemProfile || !display(row.root_display) || !display(row.target_display) || typeof row.available !== 'boolean' ||
      (row.available ? row.error_code !== null : !['target_unavailable', 'target_changed', 'target_ambiguous', 'target_unsupported'].includes(String(row.error_code)))) return false;
    ids.add(row.target_id);
    return row.scope === 'user' ? ++userCount <= 1 : row.scope === 'project' && ++projectCount <= 16;
  });
}
export function skillInstallScopeLabel(plan: SkillInstallPlan): string {
  return plan.schema_version === 'local-skill-install-plan/v2' ? (plan.target_ref.scope === 'project' ? '项目级 Skill' : '用户级 Skill') : '实例 Skill 目录';
}
// A replacement may advance its signed parent checkpoint, never its scope or root identity.
export function sameInstallTarget(previous: SkillInstallPlan, next: SkillInstallPlan): boolean {
  if (previous.schema_version !== next.schema_version) return false;
  if (previous.schema_version === 'local-skill-install-plan/v1' || next.schema_version === 'local-skill-install-plan/v1') return true;
  const a = previous.target_ref, b = next.target_ref;
  if (!['target_id', 'scope', 'filesystem_profile', 'root_locator_digest', 'root_identity_digest', 'config_root_identity_digest'].every((key) => a[key as keyof SkillInstallTargetRef] === b[key as keyof SkillInstallTargetRef])) return false;
  const parents = a.scope === 'user' ? ['', 'skills'] : ['', '.codebuddy', '.codebuddy/skills'];
  const oldDepth = parents.indexOf(a.existing_parent_relative_path), newDepth = parents.indexOf(b.existing_parent_relative_path);
  return oldDepth >= 0 && newDepth >= oldDepth && (newDepth > oldDepth || a.existing_parent_identity_digest === b.existing_parent_identity_digest);
}

export function skillInstallRequest(grant: Grant, requestId: string, directory: string, actor: string, targets: SkillInstallationTargets | null, targetId: string): SkillInstallRequest | null {
  if (grant.status !== 'approved' || !Number.isSafeInteger(grant.state_revision) || (grant.state_revision ?? -1) < 0 ||
    grant.subject.type !== 'agent_instance' || !/^hri-[a-f0-9]{32}$/.test(grant.subject.id) || !installDirectoryValid(directory) || !actor.trim()) return null;
  const common = { request_id: requestId, grant_id: grant.grant_id, expected_revision: grant.state_revision!, instance_id: grant.subject.id.replace(/^hri-/, 'hi-'), directory_name: directory, actor_id: actor.trim() };
  if (grant.platform === 'workbuddy') {
    if (grantFilesystemProfile(grant) !== windowsFilesystemProfile || !targets || targets.instance_id !== common.instance_id ||
      !targets.targets.some((target) => target.target_id === targetId && target.available && target.instance_id === common.instance_id)) return null;
    return { ...common, schema_version: 'local-skill-install-stage-create/v2', target_id: targetId };
  }
  return ['hermes', 'openclaw'].includes(grant.platform) ? { ...common, schema_version: 'local-skill-install-stage-create/v1' } : null;
}
