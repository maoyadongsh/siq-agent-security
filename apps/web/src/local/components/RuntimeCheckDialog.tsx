import { useCallback, useEffect, useState } from 'react';
import Modal from '@/components/Modal';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import type { AdapterInstances, RuntimeCheckPlan, RuntimeCheckResult } from '../types';

const statusLabel: Record<RuntimeCheckResult['status'], string> = {
  preparing: '正在准备临时授权', waiting_host: '正在启动 Hermes 测试会话', running: '正在验证正常与拒绝调用',
  passed: '本次自检通过', failed: '本次自检未通过', cancelled: '自检已取消', invalidated: '自检结果已失效',
};
const checkLabel: Record<string, string> = {
  native_session_bound: '宿主会话已绑定', allowed_read: '正常读取成功', write_denied_before_execution: '越权写入在执行前被拒',
  allowed_after_denial: '拒绝后仍可正常读取', receipt_chain_verified: '回执关联与签名验证通过',
};
const isRunning = (result: RuntimeCheckResult | null) => !!result && ['preparing', 'waiting_host', 'running'].includes(result.status);
function reasonMessage(reason: string): string {
  if (reason.includes('not_found')) return '预览已过期或被替换，请重新预览。';
  if (reason.includes('cleanup_recovered')) return '临时权限与材料已清理，可以重新预览自检。';
  if (reason.includes('configuration_not_ready') || reason.includes('native_changed')) return '请先在“管理实例”中完成此实例的原生接入，再重新预览。';
  if (reason.includes('snapshot_changed')) return '实例配置、程序或执行模式发生变化，请重新预览和自检。';
  if (reason.includes('cleanup')) return '临时权限或材料尚未完成清理，请先处理清理状态。';
  if (reason.includes('capacity')) return '当前检查记录或预览已达上限，请稍后重试。';
  if (reason.includes('conflict')) return '预览已过期，或已有自检正在运行。请刷新检查状态。';
  if (reason.includes('interrupted')) return '服务在检查期间中断，本次没有继续执行。';
  if (reason.includes('timeout')) return '宿主未在规定时间内完成检查。';
  if (reason.includes('host_failed')) return 'Hermes 测试会话未正常完成，请检查宿主安装和运行环境。';
  if (reason.includes('receipts') || reason.includes('receipt_')) return '缺少完整且匹配的运行回执，本次不能确认通过。';
  if (reason.includes('probe') || reason.includes('session_missing')) return '未取得完整的正常与拒绝调用证据。';
  if (reason.includes('forbidden_effect')) return '检测到本应拒绝的写入，本次保护检查失败。';
  return '操作未完成，请重新读取状态后重试。';
}

export default function RuntimeCheckDialog({ onClose, instanceId: requestedInstance }: { onClose: () => void; instanceId?: string }) {
  const { actorId, setActorId } = useLocalSession();
  const [catalog, setCatalog] = useState<AdapterInstances | null>(null);
  const [instanceId, setInstanceId] = useState('');
  const [plan, setPlan] = useState<RuntimeCheckPlan | null>(null);
  const [result, setResult] = useState<RuntimeCheckResult | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const running = isRunning(result);
  const close = useCallback(() => { if (!busy) onClose(); }, [busy, onClose]);

  useEffect(() => {
    let active = true;
    localApi.adapterInstances('hermes').then((data) => {
      if (!active) return;
      setCatalog(data);
      setInstanceId((current) => requestedInstance ? data.instances.find((i) => i.instance_id === requestedInstance)?.instance_id ?? '' : data.instances.some((i) => i.instance_id === current) ? current : data.instances.find((i) => i.active)?.instance_id || data.instances[0]?.instance_id || '');
      if (requestedInstance && !data.instances.some((i) => i.instance_id === requestedInstance)) { setError('未找到此安装对应的实例，请重新发现后重试。'); setLoading(false); }
      if (!data.instances.length) { setError('未发现 Hermes 实例，请先完成发现与接入。'); setLoading(false); }
    }).catch(() => { if (active) { setError('无法读取 Hermes 实例，请检查连接后重试。'); setLoading(false); } });
    return () => { active = false; };
  }, [retry, requestedInstance]);

  useEffect(() => {
    if (!instanceId) return;
    let active = true;
    setPlan(null); setResult(null); setError(''); setLoading(true);
    Promise.allSettled([localApi.runtimeCheckPreview(instanceId), localApi.runtimeCheckLatest(instanceId)]).then(([preview, latest]) => {
      if (!active) return;
      if (preview.status === 'fulfilled') setPlan(preview.value);
      else setError(reasonMessage(preview.reason instanceof Error ? preview.reason.message : ''));
      if (latest.status === 'fulfilled') setResult(latest.value.items[0] ?? null);
      else setError('无法读取已有检查状态，请重新连接后重试。');
      setLoading(false);
    });
    return () => { active = false; };
  }, [instanceId, retry]);

  const checkId = result?.check_id;
  const shouldPoll = running || result?.status === 'passed';
  useEffect(() => {
    if (!checkId || !shouldPoll) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await localApi.runtimeCheck(checkId);
        if (active) { setResult(next); setError(''); }
      } catch {
        if (active) setError('暂时无法读取自检状态，请检查服务连接；当前不能确认完成。');
      }
      if (active) timer = setTimeout(poll, running ? 1500 : 15000);
    };
    timer = setTimeout(poll, running ? 500 : 15000);
    return () => { active = false; clearTimeout(timer); };
  }, [checkId, shouldPoll, running]);

  const start = async () => {
    if (!plan || plan.instance_id !== instanceId || busy || running || loading) return;
    setBusy(true); setError('');
    try {
      setResult(await localApi.runtimeCheckStart(plan, actorId));
      setPlan(null);
    } catch (err) {
      // The server may have accepted a start whose response was lost. Read the
      // same check ID before offering another explicitly confirmed launch.
      try { setResult(await localApi.runtimeCheck(plan.check_id)); setPlan(null); }
      catch { setError(reasonMessage(err instanceof Error ? err.message : '')); setPlan(null); }
    } finally { setBusy(false); }
  };
  const cancel = async () => {
    if (!result || busy) return;
    setBusy(true); setError('');
    try { setResult(await localApi.runtimeCheckCancel(result.check_id)); }
    catch { setError('取消请求未确认，请重新读取状态。短期授权仍按服务器期限到期。'); }
    finally { setBusy(false); }
  };
  const cleanup = async () => {
    if (!result || busy) return;
    setBusy(true); setError('');
    try { setResult(await localApi.runtimeCheckCleanup(result.check_id)); }
    catch { setError('清理仍未完成。如状态事务中断，请重启本地服务完成恢复后重试。'); }
    finally { setBusy(false); }
  };

  return <Modal open onClose={close} title="Hermes · 运行自检"
    description="使用所选实例的真实配置验证工具调用。确认后才会启动新的测试会话。">
    <div className="modal-body adapter-change-body" aria-busy={loading || busy}>
      {catalog ? <div className="field">
        <label htmlFor="runtime-check-instance">自检实例 / profile</label>
        <select id="runtime-check-instance" disabled={busy || running || !!requestedInstance} value={instanceId} onChange={(e) => { setPlan(null); setResult(null); setLoading(true); setInstanceId(e.target.value); }}>
          {catalog.instances.map((i) => <option key={i.instance_id} value={i.instance_id}>{i.name} · {i.config_dir}</option>)}
        </select>
      </div> : null}
      {loading ? <p role="status">正在读取实例配置与已有检查…</p> : null}
      {error ? <p className="action-error" role="alert">{error}</p> : null}
      {result ? <div className="card" data-runtime-check-id={result.check_id} data-runtime-check-status={result.status}>
        <h3 role="status">{statusLabel[result.status]}</h3>
        <p>开始于 {new Date(result.started_at).toLocaleString()}</p>
        {result.status === 'failed' || result.status === 'invalidated' ? <p>{reasonMessage(result.reason_code)}</p> : null}
        <p>临时权限与材料：{result.cleanup === 'complete' ? '已撤权并清理' : result.cleanup === 'failed' ? '清理未完成' : '检查结束后清理'}</p>
        {result.cleanup === 'failed' ? <button type="button" className="btn" disabled={busy} onClick={cleanup}>重试清理</button> : null}
        <ul>{Object.entries(checkLabel).filter(([name]) => name in result.checks).map(([name, label]) => <li key={name}>{result.checks[name] ? '✓' : '未通过'} {label}</li>)}</ul>
        {result.receipt_ids.length ? <p>本次关联 {result.receipt_ids.length} 条回执，可在回执页追溯。</p> : null}
        {result.status === 'passed' ? <p>仅确认本次测试调用经过门禁；配置变化后需重新检查。未证明其他会话、Skill 归属或系统隔离。</p> : null}
      </div> : null}
      {plan && !running ? <>
        <h3>将执行的检查</h3><ul>{plan.effects.map((text) => <li key={text}>{text}</li>)}</ul>
        <div className="field"><label htmlFor="runtime-check-actor">确认人</label>
          <input id="runtime-check-actor" value={actorId} maxLength={128} disabled={busy} onChange={(e) => setActorId(e.target.value)} />
        </div>
      </> : null}
      <details><summary>检查范围与限制</summary><ul>{(plan?.limitations ?? result?.limitations ?? []).map((text) => <li key={text}>{text}</li>)}</ul></details>
    </div>
    <div className="modal-actions runtime-check-actions">
      <button type="button" className="btn" disabled={busy} onClick={onClose}>{running ? '关闭（后台继续）' : '关闭'}</button>
      {running ? <button type="button" className="btn btn-danger" disabled={busy} onClick={cancel}>取消自检</button> : <>
        <button type="button" className="btn" disabled={busy || loading} onClick={() => setRetry((n) => n + 1)}>重新预览</button>
        <button type="button" className="btn btn-primary" disabled={busy || loading || !!error || !plan || !actorId.trim()} onClick={start}>确认并开始自检</button>
      </>}
    </div>
  </Modal>;
}
