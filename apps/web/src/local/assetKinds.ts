/** Classify only explicit discovery facts; never infer a role from a file name. */
export type AssetKind = 'frameworks' | 'roles' | 'skills' | 'other';
export const assetKinds: { key: AssetKind; label: string; description: string }[] = [
  { key: 'frameworks', label: '智能体框架', description: '按已发现的框架和角色配置汇总，例如 Hermes、OpenClaw。同一框架的多份配置合并显示；发现配置不代表已接入保护。' },
  { key: 'roles', label: '智能体角色', description: '框架中配置的具体智能体：Hermes 的 profile、OpenClaw 的 agent。角色与所用 Skill 分开显示。' },
  { key: 'skills', label: 'Skill', description: '已发现的 Skill 目录。同名 Skill 安装在不同位置时分别管理，权限与安装内容绑定。' },
  { key: 'other', label: '其他配置', description: 'MCP 服务及其他配置记录，不计为角色或 Skill。' },
];
export function assetKind(sourceType: string): AssetKind {
  if (sourceType === 'platform_config') return 'frameworks';
  if (sourceType === 'hermes_profile' || sourceType === 'openclaw_agent') return 'roles';
  if (sourceType === 'skill_dir') return 'skills';
  return 'other';
}

export interface FrameworkGroup { framework: string; configurationRecords: number; roleCount: number }
export function frameworkGroups(rows: { framework: string; source_type: string }[]): FrameworkGroup[] {
  const groups = new Map<string, FrameworkGroup>();
  for (const row of rows) {
    const kind = assetKind(row.source_type);
    if (!['frameworks', 'roles'].includes(kind) || !row.framework || row.framework === 'unknown') continue;
    const group = groups.get(row.framework) ?? { framework: row.framework, configurationRecords: 0, roleCount: 0 };
    group.configurationRecords += 1;
    if (kind === 'roles') group.roleCount += 1;
    groups.set(row.framework, group);
  }
  return [...groups.values()].sort((a, b) => a.framework.localeCompare(b.framework));
}
