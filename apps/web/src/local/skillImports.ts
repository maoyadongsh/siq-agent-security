import type { SkillImportList, SkillImportResult } from './types';

export const importIdPattern = /^si-[a-f0-9]{32}$/;
const hash = /^[a-f0-9]{64}$/;
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string';
const count = (v: unknown, max: number): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= max;
const time = (v: unknown): boolean => text(v) && Number.isFinite(Date.parse(v));
const kind = (v: unknown): boolean => v === 'local_dir' || v === 'local_zip';

export function isSkillImportList(v: unknown): v is SkillImportList {
  if (!object(v) || (v.schema_version !== 'local-skill-import-list/v1' && v.schema_version !== 'local-skill-import-list/v2') || !Array.isArray(v.items) || v.items.length > 64) return false;
  const ids = new Set<string>();
  return v.items.every((item: unknown) => {
    if (!object(item) || !text(item.import_id) || !importIdPattern.test(item.import_id) || ids.has(item.import_id) || item.payload_status !== 'unchecked') return false;
    ids.add(item.import_id);
    if (item.record_status === 'unavailable') return item.summary === null;
    const s = item.summary;
    return item.record_status === 'metadata_verified' && object(s) && time(s.created_at) && (kind(s.source_kind) || (v.schema_version === 'local-skill-import-list/v2' && s.source_kind === 'https_zip')) && text(s.actor_id) &&
      text(s.artifact_digest) && hash.test(s.artifact_digest) && count(s.file_count, 2000) && s.file_count > 0 && count(s.total_bytes, 67108864);
  });
}

export function isSkillImportResult(v: unknown, expectedId: string): v is SkillImportResult {
  if (!object(v) || (v.schema_version !== 'local-skill-import-result/v1' && v.schema_version !== 'local-skill-import-result/v2') || v.installed !== false || typeof v.reused !== 'boolean') return false;
  const r = v.import; const a = v.admission;
  if (!object(r) || r.import_id !== expectedId || !importIdPattern.test(expectedId) ||
      !text(r.actor_id) || !time(r.created_at) || !text(r.artifact_digest) || !hash.test(r.artifact_digest) ||
      !text(r.analysis_sha256) || !hash.test(r.analysis_sha256) || typeof r.excluded_git_metadata !== 'boolean' ||
      !Array.isArray(r.directories) || r.directories.length > 2000 || !r.directories.every(text) ||
      !Array.isArray(r.files) || r.files.length === 0 || r.files.length > 2000 || !r.files.every((f: unknown) => object(f) &&
        text(f.path) && text(f.sha256) && hash.test(f.sha256) && count(f.bytes, 8388608) && typeof f.executable === 'boolean')) return false;
  if (v.schema_version === 'local-skill-import-result/v1') {
    if (r.schema_version !== 'local-skill-import/v1' || !kind(r.source_kind) || r.remote !== undefined) return false;
  } else {
    const m = r.remote;
    if (r.schema_version !== 'local-skill-import/v2' || r.source_kind !== 'https_zip' || !object(m) ||
      !text(m.archive_sha256) || !hash.test(m.archive_sha256) || !count(m.archive_bytes, 33554432) || m.archive_bytes === 0 ||
      !text(m.final_locator_digest) || !hash.test(m.final_locator_digest) || !text(m.archive_path) || m.archive_path.length > 512 ||
      !text(m.expected_sha256) || (m.expected_sha256 !== '' && m.expected_sha256 !== m.archive_sha256)) return false;
  }
  return object(a) && text(a.skill_name) && text(a.admission_id) && text(a.content_hash) && hash.test(a.content_hash) && time(a.decided_at) &&
    ['admit', 'admit_with_conditions', 'quarantine'].includes(String(a.verdict)) &&
    Array.isArray(a.declared_facts) && a.declared_facts.every((f: unknown) => object(f) && text(f.domain) && text(f.action) &&
      text(f.state) && text(f.effect) && object(f.resource) && text(f.resource.type) && text(f.resource.value)) &&
    Array.isArray(a.findings) && a.findings.every((f: unknown) => object(f) && text(f.finding_id) && text(f.rule_id) && text(f.severity) &&
      (f.excerpt === undefined || f.excerpt === null || (text(f.excerpt) && f.excerpt.length <= 1000)) &&
      (f.location === undefined || (object(f.location) && text(f.location.path) && (f.location.line === null || count(f.location.line, Number.MAX_SAFE_INTEGER)))));
}

export function newImportId(): string {
  return 'si-' + Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function skillImportErrorText(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  const messages: Record<string, string> = {
    skill_import_permission_invalid: '无法准备权限，请检查目标实例和操作者信息。',
    skill_import_permission_source_invalid: '此候选无法用于权限准备。请确认检查结论、签名与内容均有效，隔离候选不能授权。',
    skill_import_permission_target_unavailable: '目标 Hermes 实例已不可用，请重新检查实例列表。',
    skill_import_invalid: '无法导入。请检查来源、归档内的 Skill 目录、预期摘要，以及 ZIP 内的路径和文件类型。所选目录须包含 SKILL.md。',
    skill_import_url_blocked: '下载链接不符合要求。请使用公网 HTTPS ZIP 链接；暂不支持内网地址、非标准端口、账号密码或重定向到这些地址。',
    skill_import_download_failed: '下载未完成。请检查链接是否直接返回 ZIP、是否需要登录，以及网络和证书是否正常，然后重试。',
    skill_import_archive_mismatch: '下载内容与预期 SHA256 不一致，未保存候选。请向来源方核实版本和摘要。',
    skill_import_limit: '导入内容或候选数量超过上限。单个文件最多 8 MiB，内容合计 64 MiB，ZIP 最多 32 MiB；最多保存 64 个候选。',
    skill_import_changed: '记录或副本发生变化，无法确认完整性。请检查来源后开始新的导入。',
    skill_import_conflict: '这个导入编号对应其他请求。请先查询结果，或明确开始新的导入。',
    skill_import_not_found: '未找到已保存的导入结果。操作可能尚未完成；可稍后查询，或使用原请求重试。',
    skill_import_interrupted: '导入已中断或超时。请先查询结果，确认是否已保存。',
    skill_import_busy: '另一个导入或校验正在进行。请稍后重试。',
    skill_import_unavailable: '无法读取或保存导入记录。请检查本地服务和状态目录的可用空间。',
  };
  return messages[code] ?? (code.startsWith('skill_import_') ? '导入暂时不可用，请查询记录或检查本地服务。' :
    '无法确认导入结果。请检查本地服务是否已启动且版本匹配，然后查询记录。');
}
