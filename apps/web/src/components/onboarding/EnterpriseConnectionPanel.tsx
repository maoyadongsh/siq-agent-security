import { useEffect, useRef, useState } from 'react';
import { ApiError } from '@/api/client';
import { inspectEnterpriseConnection, type EnterpriseConnection } from '@/api/enterpriseConnection';

const labels: Record<EnterpriseConnection['status'], string> = {
  not_configured: '尚未配置控制面 OpenShell 连接，请联系部署管理员。',
  configuration_rejected: '连接配置未通过安全检查，请由部署管理员核对 HTTPS、CLI 路径及文件权限；不要关闭 TLS 校验。',
  probe_failed: '本次连接检查失败，不能沿用之前的成功结果。',
  identity_unverified: '响应身份未确认，不能视为 OpenShell 连接成功。',
  version_unknown: '握手已确认，但网关版本未知；版本兼容性未核验。',
  handshake_verified: '本次握手已确认；不代表沙箱已绑定或权限已生效。',
};
export function ConnectionDetails({ value }: { value: EnterpriseConnection }) {
  return <div aria-live="polite">
    <p>{labels[value.status]}</p>
    <p>版本兼容性、最小凭据范围和实际执行效果尚未验证，不能据此开始部署。</p>
    {value.endpoint_fingerprint ? <details>
      <summary>查看连接证据摘要</summary>
      <dl className="kv-list">
        <dt>CLI 版本</dt><dd>{value.cli_version}</dd>
        <dt>网关版本</dt><dd>{value.gateway_version}</dd>
        <dt>调用指纹</dt><dd className="mono">{value.endpoint_fingerprint}</dd>
        <dt>网关名称摘要</dt><dd className="mono">{value.gateway_name_sha256}</dd>
      </dl>
      <p>适配器配置表达能力不等于当前沙箱已执行验证。</p>
    </details> : null}
  </div>;
}
export default function EnterpriseConnectionPanel({ environmentId }: { environmentId: string }) {
  const [value, setValue] = useState<EnterpriseConnection>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  async function inspect() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setValue(undefined); setError('');
    try {
      const result = await inspectEnterpriseConnection(environmentId);
      if (live.current) setValue(result);
    } catch (reason) {
      if (live.current) setError(reason instanceof ApiError && reason.status === 403
        ? '当前账号缺少环境管理或策略读取权限，请联系组织管理员。'
        : '未获得可核验的诊断结果，请手动重试；不会自动重复探测。');
    } finally {
      pending.current = false;
      if (live.current) setBusy(false);
    }
  }
  return <details className="card role-skill-panel">
    <summary>高级诊断：OpenShell 控制面连接</summary>
    <p>仅检查控制面已配置的连接，不证明网关或沙箱属于当前环境。不会创建沙箱、发布策略或授予智能体权限。</p>
    <button className="btn" disabled={busy} onClick={inspect}>{busy ? '正在检查…' : '检查 OpenShell 连接'}</button>
    {busy ? <p role="status">正在只读检查，请稍候…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {value ? <ConnectionDetails value={value} /> : null}
  </details>;
}
