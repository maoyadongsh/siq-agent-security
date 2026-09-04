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
    default:
      return name;
  }
}

export function shortHash(h: string | undefined, n = 12): string {
  if (!h) return '—';
  return h.length <= n ? h : `${h.slice(0, n)}…`;
}
