export function verdictTag(v: string): string {
  if (v === 'quarantine') return 'tag tag-err';
  if (v === 'admit_with_conditions') return 'tag tag-warn';
  if (v === 'admit') return 'tag tag-ok';
  return 'tag';
}

export function grantTag(v: string): string {
  if (v === 'rejected' || v === 'revoked') return 'tag tag-err';
  if (v === 'pending_approval') return 'tag tag-warn';
  if (v === 'effective' || v === 'deployed' || v === 'approved') return 'tag tag-ok';
  return 'tag';
}

export function actionTag(v: string): string {
  if (v === 'deny') return 'tag tag-err';
  if (v === 'hold' || v === 'redact') return 'tag tag-warn';
  if (v === 'allow') return 'tag tag-ok';
  return 'tag';
}

export function hasOpenShellL3(platforms: { name: string; tier: string }[] | undefined): boolean {
  return (platforms ?? []).some((p) => p.name === 'openshell' && p.tier === 'L3');
}

export function platformTierText(
  p: { name: string; tier: string },
  openShellL3: boolean,
): string {
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

export function shortHash(h: string | undefined, n = 12): string {
  if (!h) return '—';
  return h.length <= n ? h : `${h.slice(0, n)}…`;
}

export function assetStatusTag(status: string): string {
  if (status === 'quarantined' || status === 'stale') return 'tag tag-err';
  if (status === 'unadmitted' || status === 'needs_review' || status === 'dismissed') return 'tag tag-warn';
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
