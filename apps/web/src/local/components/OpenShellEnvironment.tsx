import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { localApi } from '../api';
import type { OpenShellTargets, OpenShellInspection } from '../openshellDiscovery';
import type { RegisteredGateway } from '../openshellGateways';
import OpenShellGateways from './OpenShellGateways';

const sourceLabel: Record<string, string> = { none: '未配置', invalid: '配置不完整', path: '系统命令路径', env_sh: '现有启动脚本', env_pair: '已指定的 CLI 与网关' };
const phaseLabel: Record<string, string> = { Ready: '就绪', Running: '运行中', Pending: '等待中', Creating: '创建中', Stopping: '停止中', Stopped: '已停止', Error: '异常', Terminated: '已终止', Unknown: '状态未知' };
const stateLabel: Record<string, string> = { unconfigured: '尚未配置', unreachable: '网关未连接', catalog_unavailable: '网关可达，清单未取得', available: '已读取网关清单' };

export default function OpenShellEnvironment({ refreshKey = '' }: { refreshKey?: string }) {
  return <OpenShellGateways refreshKey={refreshKey}>{(gateway) => <GatewayEnvironment key={gateway ? `${gateway.gateway_id}:${gateway.configuration_fingerprint}` : 'configured'} gateway={gateway} refreshKey={refreshKey} />}</OpenShellGateways>;
}

function GatewayEnvironment({ refreshKey, gateway }: { refreshKey: string; gateway?: RegisteredGateway }) {
  const [catalog, setCatalog] = useState<OpenShellTargets>();
  const [selected, setSelected] = useState('');
  const [result, setResult] = useState<OpenShellInspection>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [reading, setReading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const inspectRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    inspectRequest.current?.abort(); inspectRequest.current = null; setReading(false);
    setLoading(true); setError(''); setResult(undefined); setCatalog(undefined);
    const request = gateway ? localApi.openshellGatewayTargets(gateway, controller.signal) : localApi.openshellTargets(controller.signal);
    request.then((data) => {
      if (controller.signal.aborted) return;
      setCatalog(data); setSelected((id) => data.items.some((item) => item.sandbox_id === id) ? id : data.items[0]?.sandbox_id ?? '');
    }).catch(() => { if (!controller.signal.aborted) setError('暂时无法读取 OpenShell 环境，请重新发现。'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshKey, attempt, gateway]);
  useEffect(() => () => inspectRequest.current?.abort(), []);
  useEffect(() => {
    if (!result) return;
    setNow(Date.now()); const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [result]);
  const inspect = async () => {
    const item = catalog?.items.find((row) => row.sandbox_id === selected);
    if (!catalog || !item || !catalog.can_inspect || inspectRequest.current || loading) return;
    const controller = new AbortController(); inspectRequest.current = controller;
    setReading(true); setError(''); setResult(undefined);
    try { const data = await (gateway ? localApi.openshellGatewayInspect(gateway, item, catalog, controller.signal) : localApi.openshellInspectTarget(item, catalog, controller.signal)); if (!controller.signal.aborted) setResult(data); }
    catch { if (!controller.signal.aborted) setError('目标、网关或策略可能已变化。请重新发现后再读取，未修改任何配置。'); }
    finally { if (inspectRequest.current === controller) inspectRequest.current = null; if (!controller.signal.aborted) setReading(false); }
  };
  return <section className="block-gap openshell-environment" aria-label="OpenShell 环境发现">
    <div className="toolbar"><h3>OpenShell 隔离环境</h3>
      <button type="button" className="btn btn-sm" disabled={loading || reading} onClick={() => setAttempt((n) => n + 1)}>重新发现 OpenShell</button>
    </div>
    {loading ? <p role="status">正在读取现有 OpenShell 配置与网关…</p> : null}
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    {catalog ? <>
      <p role="status">{stateLabel[catalog.state]}{catalog.gateway ? ` · ${catalog.gateway}` : ''}</p>
      <p className="page-desc">来源：{gateway ? '已登记网关' : sourceLabel[catalog.source]} · 检查于 {new Date(catalog.observed_at).toLocaleString('zh-CN', { hour12: false })}
        {catalog.cli_version ? ` · CLI ${catalog.cli_version}` : ''}</p>
      {catalog.state === 'unconfigured' ? <p>未发现可用的 OpenShell 配置。可继续使用智能体接入和权限管理。</p> : null}
      {catalog.state === 'unreachable' ? <p>已读取现有配置，但尚未确认网关连接。请核对当前 CLI 来源和网关配置后重试。</p> : null}
      {catalog.state === 'catalog_unavailable' ? <p>网关握手成功，但沙箱列表读取失败、协议不兼容或超过完整清单上限。不能将其视为空环境。</p> : null}
      {catalog.state === 'available' && !catalog.items.length ? <p>当前网关没有沙箱。此结果不代表其他网关也为空。</p> : null}
      {catalog.items.length ? <>
        <div className="field"><label htmlFor="discovered-openshell-target">选择沙箱</label>
          <select id="discovered-openshell-target" value={selected} disabled={reading} onChange={(e) => { setSelected(e.target.value); setResult(undefined); setError(''); }}>
            {catalog.items.map((item) => <option key={item.sandbox_id} value={item.sandbox_id}>{item.name} · {phaseLabel[item.phase]}</option>)}
          </select>
        </div>
        <button type="button" className="btn" disabled={!catalog.can_inspect || reading || loading} onClick={inspect}>{reading ? '正在读取策略…' : '读取当前策略'}</button>
        {!catalog.can_inspect ? <p>当前配置未固定网关端点，只展示发现结果。指定 CLI 与网关后才能核对单个沙箱策略。</p> : null}
      </> : null}
    </> : null}
    {result ? <div className="notice" role="status">
      <strong>{result.name}：{now >= Date.parse(result.expires_at) ? '上次策略读回已过期' : '当前策略已读回'}</strong>
      <p>策略版本 {result.revision}。未验证实际隔离效果；需要更新结果时再次读取。</p>
      <details><summary>查看核对信息</summary><p>沙箱 ID：<code>{result.sandbox_id}</code></p><p>策略摘要：<code>{result.policy_digest}</code></p></details>
    </div> : null}
    <p className="page-desc">发现和读取均为只读操作。网关可达、沙箱就绪或策略可读，都不代表智能体已在沙箱中运行或隔离已验证。<Link to="/settings">查看运行配置</Link></p>
  </section>;
}
