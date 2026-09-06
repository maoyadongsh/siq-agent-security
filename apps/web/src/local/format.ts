/** siq-agent-security 本地控制台展示助手：状态 → 中文标签 / 语义 tag 类名。 */

export function verdictTag(v: string): string {
  if (v === 'quarantine') return 'tag tag-err';
  if (v === 'admit_with_conditions') return 'tag tag-warn';
  if (v === 'admit') return 'tag tag-ok';
  return 'tag';
}

export function verdictLabel(v: string): string {
  switch (v) {
    case 'admit':
      return '准入';
    case 'admit_with_conditions':
      return '有条件准入';
    case 'quarantine':
      return '隔离';
    default:
      return v;
  }
}

/** grant 状态：approved 是人工里程碑（绿）；deployed 只是已下发未读回，不给「有效」的绿色。 */
export function grantTag(v: string): string {
  if (v === 'rejected' || v === 'revoked') return 'tag tag-err';
  if (v === 'pending_approval') return 'tag tag-warn';
  if (v === 'approved') return 'tag tag-ok';
  if (v === 'deployed') return 'tag tag-info';
  return 'tag';
}

export function grantStatusLabel(v: string): string {
  switch (v) {
    case 'pending_approval':
      return '待批准';
    case 'approved':
      return '已批准';
    case 'deployed':
      return '已部署 · 未读回';
    case 'rejected':
      return '已拒绝';
    case 'revoked':
      return '已吊销';
    default:
      return v;
  }
}

export function actionTag(v: string): string {
  if (v === 'deny') return 'tag tag-err';
  if (v === 'hold' || v === 'redact') return 'tag tag-warn';
  if (v === 'allow') return 'tag tag-ok';
  return 'tag';
}

export function actionLabel(v: string): string {
  switch (v) {
    case 'allow':
      return '放行';
    case 'deny':
      return '拒绝';
    case 'hold':
      return '挂起';
    case 'redact':
      return '脱敏';
    default:
      return v;
  }
}

export function severityTag(sev: string): string {
  if (sev === 'critical' || sev === 'high') return 'tag tag-err';
  if (sev === 'medium') return 'tag tag-warn';
  if (sev === 'low' || sev === 'info') return 'tag tag-info';
  return 'tag';
}

export function severityLabel(sev: string): string {
  switch (sev) {
    case 'critical':
      return '严重';
    case 'high':
      return '高';
    case 'medium':
      return '中';
    case 'low':
      return '低';
    case 'info':
      return '提示';
    default:
      return sev;
  }
}

export function findingStatusTag(status: string): string {
  if (status === 'open' || !status) return 'tag tag-warn';
  if (status === 'accepted') return 'tag';
  return 'tag';
}

export function findingStatusLabel(status: string): string {
  if (status === 'accepted') return '已接受';
  if (status === 'open' || !status) return '待处理';
  return status;
}

/** disposition 枚举来自 admission.schema.json：quarantine / declare / info。 */
export function dispositionLabel(d: string): string {
  switch (d) {
    case 'quarantine':
      return '隔离';
    case 'declare':
      return '升级为声明';
    case 'info':
      return '仅记录';
    default:
      return d;
  }
}

export function hasOpenShellL3(platforms: { name: string; tier: string }[] | undefined): boolean {
  return (platforms ?? []).some((p) => p.name === 'openshell' && p.tier === 'L3');
}

export function platformTierText(
  p: { name: string; tier: string },
  openShellL3: boolean,
): string {
  if (p.name === 'trae') return `${platformLabel(p.name)} · 审计模式 · 无法阻断`;
  const base = `${platformLabel(p.name)} · ${p.tier}`;
  if (p.tier === 'L2' && !openShellL3) {
    return `${base} · 仅工具层拦截`;
  }
  return base;
}

export function platformLabel(name: string): string {
  switch (name) {
    case 'openclaw':
      return 'OpenClaw';
    case 'hermes':
      return 'Hermes';
    case 'codebuddy':
      return 'CodeBuddy';
    case 'trae':
      return 'Trae';
    case 'openshell':
      return 'OpenShell';
    default:
      return name;
  }
}

/** 适配器状态（Go adapterinstall.Status 的 note 原值）→ 中文。 */
export function adapterLabel(adapter: string): string {
  switch (adapter) {
    case 'installed':
      return '已安装';
    case 'not installed':
      return '未安装';
    case 'audit_only':
      return '仅审计';
    case 'unknown':
      return '未知';
    default:
      return adapter || '未知';
  }
}

export function adapterTag(adapter: string): string {
  if (adapter === 'installed') return 'tag tag-ok';
  if (adapter === 'audit_only') return 'tag tag-info';
  return 'tag';
}

export function shortHash(h: string | undefined, n = 12): string {
  if (!h) return '—';
  return h.length <= n ? h : `${h.slice(0, n)}…`;
}

/** 资产状态色：未准入与隔离是需要立刻处理的红；已驳回是人类的安静决定（中性）。 */
export function assetStatusTag(status: string): string {
  if (status === 'quarantined' || status === 'stale' || status === 'unadmitted') return 'tag tag-err';
  if (status === 'needs_review') return 'tag tag-warn';
  if (status === 'admitted' || status === 'confirmed' || status === 'managed') return 'tag tag-ok';
  return 'tag';
}

export function assetStatusLabel(status: string): string {
  switch (status) {
    case 'unadmitted':
      return '未准入';
    case 'quarantined':
      return '已隔离';
    case 'admitted':
      return '已准入';
    case 'candidate':
      return '候选';
    case 'confirmed':
      return '已确认';
    case 'managed':
      return '已纳管';
    case 'dismissed':
      return '已驳回';
    case 'needs_review':
      return '待复核';
    case 'stale':
      return '已过期';
    default:
      return status;
  }
}

export const DOMAIN_LABELS: Record<string, string> = {
  filesystem: '文件',
  network: '网络',
  process: '进程',
  model: '模型',
  credential: '凭据',
  data_scope: '数据范围',
  tool: '工具',
  business: '业务',
  resource: '资源',
  control_plane: '控制面',
};

export function domainLabel(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain;
}

export function factStateTag(state: string): string {
  return `state-tag ${state}`;
}

export function factStateLabel(state: string): string {
  switch (state) {
    case 'effective':
      return '有效';
    case 'declared':
      return '声明';
    case 'inferred':
      return '推断';
    case 'observed':
      return '观测';
    case 'unknown':
      return '未知';
    default:
      return state;
  }
}
