import type { AdapterInstances, AdapterPlan, AdapterResult, Grant } from './types';

export function verifyAdapterResult(plan: AdapterPlan, result: AdapterResult): void {
  if (result.platform !== plan.platform || result.action !== plan.action) throw new Error('应用结果与预览不一致，请重新读取实例状态。');
}

export function verifyAdapterReadback(plan: AdapterPlan, catalog: AdapterInstances): void {
  const instance = catalog.instances.find((item) => item.instance_id === plan.instance_id);
  if (!instance) throw new Error('配置操作已返回，但未能读回此实例；请刷新诊断。');
  const diagnosis = instance.diagnosis;
  const expected = plan.action === 'uninstall' ? ['not_installed'] : ['ready', 'needs_verification'];
  if (!expected.includes(diagnosis.configuration_state) || diagnosis.checks.some((check) => check.status === 'fail')) {
    throw new Error('配置操作已返回，但配置读回尚未通过；请查看实例诊断并重新预览。');
  }
}

export function verifyDeployedGrant(applied: Grant, current: Grant): void {
  if (applied.grant_id !== current.grant_id || applied.state_revision === undefined
    || current.state_revision !== applied.state_revision || !['deployed', 'effective'].includes(current.status)) {
    throw new Error('授权部署尚未核验或已发生变化，请重新核对最新权限。');
  }
}

export function grantExpiryLabel(expiresAt: string | null | undefined): string {
  if (expiresAt === null) return '未设置到期时间';
  if (!expiresAt || !Number.isFinite(Date.parse(expiresAt))) return '未知，请刷新授权状态';
  return new Date(expiresAt).toLocaleString();
}
