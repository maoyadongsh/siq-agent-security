/**
 * DEV13-C：部署验证展示合同。
 * - 配置读回 ≠ 行为/阻断已验证；
 * - 不得因 deployment.status=effective 就暗示阻断已验证。
 */

export type VerificationUiKind =
  | 'none'
  | 'pending'
  | 'config_readback'
  | 'behavior_enforced'
  | 'failed'
  | 'stale'
  | 'unknown';

export interface VerificationView {
  kind: VerificationUiKind;
  /** 主文案（用户可见） */
  label: string;
  /** 补充（level/method/时间等，可空） */
  detail: string;
  tone: 'neutral' | 'ok' | 'warn' | 'err';
}

const LEVEL_ALIASES: Record<string, VerificationUiKind> = {
  readback_verified: 'config_readback',
  config_readback: 'config_readback',
  enforcement_verified: 'behavior_enforced',
  behavior_verified: 'behavior_enforced',
  failed: 'failed',
  error: 'failed',
  stale: 'stale',
  expired: 'stale',
};

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/**
 * 将部署 status + verification JSON 归一为 UI 态。
 * verification 缺失时不得冒充已读回/已阻断。
 */
export function classifyDeploymentVerification(
  deploymentStatus: string,
  verification: unknown,
): VerificationView {
  const status = (deploymentStatus || '').toLowerCase();
  if (status === 'deploying' || status === 'pending' || status === 'in_progress') {
    return { kind: 'pending', label: '验证进行中', detail: status, tone: 'warn' };
  }

  const v = asRecord(verification);
  if (!v) {
    if (status === 'failed') {
      return { kind: 'failed', label: '部署失败', detail: '无 verification 载荷', tone: 'err' };
    }
    if (status === 'effective') {
      return {
        kind: 'none',
        label: '未验证',
        detail: '业务已生效但无验证载荷（不得视为阻断已验证）',
        tone: 'warn',
      };
    }
    return { kind: 'none', label: '未验证', detail: '', tone: 'neutral' };
  }

  if (v.stale === true || v.expired === true) {
    return {
      kind: 'stale',
      label: '证据过期/陈旧',
      detail: [str(v.level), str(v.verified_at)].filter(Boolean).join(' · '),
      tone: 'err',
    };
  }

  const levelRaw = str(v.level) ?? str(v.verification_level) ?? '';
  const kind = LEVEL_ALIASES[levelRaw.toLowerCase()] ?? (levelRaw ? 'unknown' : 'none');
  const method = str(v.method);
  const verifiedAt = str(v.verified_at) ?? str(v.at);
  const extras = [levelRaw || null, method, verifiedAt].filter(Boolean).join(' · ');

  switch (kind) {
    case 'config_readback':
      return {
        kind,
        label: '配置已读回',
        detail: extras || '不证明行为阻断',
        tone: 'ok',
      };
    case 'behavior_enforced':
      return {
        kind,
        label: '阻断已验证',
        detail: extras,
        tone: 'ok',
      };
    case 'failed':
      return {
        kind,
        label: '验证失败',
        detail: extras || str(v.error) || '',
        tone: 'err',
      };
    case 'stale':
      return { kind, label: '证据过期/陈旧', detail: extras, tone: 'err' };
    case 'none':
      return { kind: 'none', label: '未验证', detail: extras, tone: 'neutral' };
    default:
      return {
        kind: 'unknown',
        label: '验证状态未知',
        detail: extras || '无法识别的 verification.level',
        tone: 'warn',
      };
  }
}

/** 权限事实五态展示（declared/inferred/observed/effective/unknown）。 */
export const PERMISSION_STATE_LABELS: Record<string, string> = {
  declared: '声明',
  inferred: '推断',
  observed: '观测',
  effective: '生效',
  unknown: '未知',
};

export function permissionStateLabel(state: string): string {
  return PERMISSION_STATE_LABELS[state] ?? state;
}
