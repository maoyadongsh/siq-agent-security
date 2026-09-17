import type { SkillImportSourceKind, SkillUpdateContent } from './types';
export interface SkillUpdateCheckRequest { schema_version: 'local-skill-update-check/v1'; remote_url: string; actor_id: string }
export interface SkillUpdateSourceRequest { schema_version: 'local-skill-update-source-save/v1'; remote_url: string; enable: boolean; actor_id: string }
export interface SkillUpdateSourceDisableRequest { schema_version: 'local-skill-update-source-disable/v1'; actor_id: string }
export interface SkillUpdateCheckResult {
  schema_version: 'local-skill-update-check-result/v1'; install_id: string; checked_at: string;
  status: 'up_to_date' | 'new_version'; source_kind: 'git' | 'https_zip';
  upstream_commit_sha?: string; upstream_archive_sha256?: string;
  content_changes: { path_display: string; path_digest: string; before: SkillUpdateContent | null; after: SkillUpdateContent | null }[];
  content_changes_total: number; content_changes_truncated: boolean; requires_confirmation: boolean;
  permission_comparison: 'deferred_to_update_comparison';
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const hex = (v: unknown, n: number) => typeof v === 'string' && new RegExp(`^[a-f0-9]{${n}}$`).test(v);
const content = (v: unknown) => v === null || (object(v) && Object.keys(v).sort().join() === 'bytes,executable,kind,sha256' &&
  Number.isSafeInteger(v.bytes) && Number(v.bytes) >= 0 && Number(v.bytes) <= 8388608 && typeof v.executable === 'boolean' &&
  (v.kind === 'directory' ? v.sha256 === '' && v.bytes === 0 && v.executable === false : v.kind === 'file' && hex(v.sha256, 64)));
export function isSkillUpdateCheckResult(v: unknown, id: string): v is SkillUpdateCheckResult {
  if (!object(v) || v.schema_version !== 'local-skill-update-check-result/v1' || v.install_id !== id || !/^sin-[a-f0-9]{64}$/.test(id) ||
    typeof v.checked_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T/.test(v.checked_at) || !Number.isFinite(Date.parse(v.checked_at)) ||
    v.permission_comparison !== 'deferred_to_update_comparison' || !Number.isSafeInteger(v.content_changes_total) || Number(v.content_changes_total) < 0 ||
    !Array.isArray(v.content_changes)) return false;
  const required = 'schema_version install_id checked_at status source_kind content_changes content_changes_total content_changes_truncated requires_confirmation permission_comparison'.split(' ');
  const digest = v.source_kind === 'git' ? 'upstream_commit_sha' : v.source_kind === 'https_zip' ? 'upstream_archive_sha256' : '';
  if (!digest || !hex(v[digest], v.source_kind === 'git' ? 40 : 64) || Object.keys(v).length !== required.length + 1 ||
    !required.every((k) => k in v)) return false;
  const total = Number(v.content_changes_total);
  if (v.content_changes.length !== Math.min(200, total) || v.content_changes_truncated !== (total > 200) ||
    v.status !== (total ? 'new_version' : 'up_to_date') || v.requires_confirmation !== (total > 0)) return false;
  return v.content_changes.every((c) => object(c) && Object.keys(c).sort().join() === 'after,before,path_digest,path_display' &&
    typeof c.path_display === 'string' && c.path_display.length > 0 && [...c.path_display].length <= 1024 &&
    !/[\u0000-\u001f\u007f]/.test(c.path_display) && hex(c.path_digest, 64) && (c.before !== null || c.after !== null) && content(c.before) && content(c.after));
}
export interface SkillUpdateScheduleView {
  schema_version: 'local-skill-update-schedule-view/v1'; install_id: string;
  source_kind: SkillImportSourceKind; display: string; enabled: boolean;
  source_state: 'saved' | 'needs_source' | 'unsupported' | 'stale';
  status: 'not_checked' | 'checking' | 'up_to_date' | 'new_version' | 'source_unavailable' | 'unsupported';
  failure_category?: string; next_check_at?: string; last_attempt_at?: string; last_success_at?: string;
}
const timestamp = (v: unknown) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v) && Number.isFinite(Date.parse(v));
// Display is the scheme://host/path form only: no query, fragment or userinfo,
// so credentials or tokens carried in a saved URL are never echoed to the UI.
const displayURL = (v: unknown) => typeof v === 'string' && v.length > 0 && [...v].length <= 512 &&
  /^https?:\/\/[^/?#@\s]+\/[^?#\s]*$/.test(v) && !/[\u0000-\u001f\u007f]/.test(v);
export function isSkillUpdateScheduleView(v: unknown, id: string): v is SkillUpdateScheduleView {
  if (!object(v) || v.schema_version !== 'local-skill-update-schedule-view/v1' || v.install_id !== id || !/^sin-[a-f0-9]{64}$/.test(id) ||
    typeof v.enabled !== 'boolean') return false;
  const states = ['saved', 'needs_source', 'unsupported', 'stale'];
  const statuses = ['not_checked', 'checking', 'up_to_date', 'new_version', 'source_unavailable', 'unsupported'];
  const kinds = ['git', 'https_zip', 'local_dir', 'local_zip'];
  if (!states.includes(v.source_state as string) || !statuses.includes(v.status as string) || !kinds.includes(v.source_kind as string)) return false;
  const optional = ['failure_category', 'next_check_at', 'last_attempt_at', 'last_success_at'].filter((k) => k in v);
  const required = 'schema_version install_id source_kind display enabled source_state status'.split(' ');
  if (Object.keys(v).length !== required.length + optional.length || !required.every((k) => k in v)) return false;
  // Optional scheduling fields and a display locator only exist for a saved,
  // enabled-capable source; every other state stays minimal and non-committal.
  const saved = v.source_state === 'saved' && v.source_kind !== 'local_dir' && v.source_kind !== 'local_zip';
  if (saved ? !displayURL(v.display) : v.display !== '') return false;
  if (!saved && (optional.length > 0 || v.enabled)) return false;
  return optional.every((k) => k === 'failure_category'
    ? typeof v[k] === 'string' && v[k].length > 0 && [...v[k]].length <= 64
    : timestamp(v[k]));
}

export type SkillUpdateSourceTogglePlan =
  | { kind: 'disable' }
  | { kind: 'save'; remoteURL: string }
  | { kind: 'error'; message: string };

// A saved enabled source always uses the URL-free disable endpoint. Enabling
// still follows the original binding rules: Git uses its signed import record,
// while HTTPS ZIP must be explicitly supplied again.
export function planSkillUpdateSourceToggle(view: SkillUpdateScheduleView, remoteURL: string): SkillUpdateSourceTogglePlan {
  if (view.source_state === 'unsupported') return { kind: 'error', message: '此安装来源不支持自动检查。' };
  if (view.source_state === 'stale') return { kind: 'error', message: '已保存来源与当前安装不一致，请先重新绑定来源。' };
  if (view.source_state === 'saved' && view.enabled) return { kind: 'disable' };
  if (view.source_kind === 'git') return { kind: 'save', remoteURL: '' };
  const trimmed = remoteURL.trim();
  if (trimmed) return { kind: 'save', remoteURL: trimmed };
  return { kind: 'error', message: '启用 HTTPS ZIP 自动检查前，请先在下方填写原下载链接。' };
}

export function isCurrentSkillUpdateRequest(ownerIdentity: string, currentIdentity: string, aborted: boolean): boolean {
  return !aborted && ownerIdentity === currentIdentity;
}
export function updateCheckErrorText(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  const messages: Record<string, string> = {
    skill_update_source_unavailable: '暂时无法从上游获取内容。请检查网络与代理设置，确认来源公开可见，然后重试；此次未完成检查。',
    skill_update_source_not_configured: '尚未保存自动检查来源，请先保存来源后再操作。',
    skill_update_url_blocked: '链接未通过安全检查，请使用原 HTTPS 下载链接；不接受内网或本机地址。',
    skill_install_unavailable: '暂时无法获取上游，请检查网络与本地服务后重试。此次未完成检查。',
    skill_install_changed: '来源链接或安装记录与原记录不一致，请核对原下载链接和安装记录。',
    skill_install_invalid: '此安装的来源不支持新版检查。HTTPS ZIP 来源请填写原下载链接；本地目录或 ZIP 来源没有可检查的上游。',
    skill_install_removal_pending: '此安装已进入移除流程，请先处理原移除操作。',
    skill_install_busy: '正在处理其他候选，请稍后重试。',
    skill_install_limit: '上游内容超出检查限额，未完成检查。',
    skill_install_interrupted: '检查已中断，可以重新检查。',
    skill_install_not_found: '安装记录不存在，请刷新列表。',
  };
  return messages[code] ?? '未能确认新版检查结果，请检查连接后重试。';
}
