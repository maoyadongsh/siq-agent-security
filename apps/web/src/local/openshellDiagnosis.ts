export interface OpenShellDiagnosis {
  state?: string;
  expires_at?: string;
  human_next?: string;
  source?: string;
  cli_found?: boolean;
  identity_ok?: boolean;
  started_gateway?: boolean;
}

// A successful protocol response is not an isolation attestation.
export function openshellDiagnosisLabel(d?: OpenShellDiagnosis, now = Date.now()): string {
  const expiry = d?.expires_at ? Date.parse(d.expires_at) : NaN;
  if (d?.expires_at && (!Number.isFinite(expiry) || expiry <= now)) return '证据已过期，请重新检查';
  switch (d?.state) {
    case 'unconfigured': return '未配置 OpenShell';
    case 'configured_unreachable': return '已配置，服务不可达';
    case 'identity_unconfirmed': return '响应身份或协议未确认';
    case 'handshake_verified': return '协议响应已确认；执行限制尚未验证';
    case 'policy_readable': return '目标策略已读回；执行限制尚未验证';
    case 'evidence_expired': return '证据不可用或已过期，请重新检查';
    // No current CLI producer can attest behavioral enforcement.
    default: return '保护能力尚未确认';
  }
}
