import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '@/api/client';
import { getRoleSkillHistory, type RoleSkillHistory, type RoleSkillSelection } from '@/api/roleSkillSelections';

export function SelectionDescription({ selection }: { selection: RoleSkillSelection }) {
  if (selection.status === 'unconfigured') return <p>未配置技能范围筛选，不代表没有技能或已经授予全部权限。</p>;
  if (selection.status === 'unsupported') return <p>声明无法安全解析，技能范围未知；不回退到默认范围。</p>;
  if (!selection.names.length) return <p>显式空范围：此声明未选择任何技能，不代表技能已卸载或执行权限已撤销。</p>;
  return <><p>声明可见的技能名称（{selection.names.length}）</p>
    <ul>{selection.names.map(name => <li key={name}><code>{name}</code></li>)}</ul></>;
}

const sourceLabel = { agent: '角色显式声明', defaults: '继承框架默认范围', none: '未配置' };

export function RoleSkillHistoryDetails({ history }: { history: RoleSkillHistory }) {
  const [selectedId, setSelectedId] = useState(history.observations[0]?.id ?? '');
  const selected = history.observations.find(o => o.id === selectedId);
  if (!selected) return <p>尚无可追溯的技能范围声明。当前支持 OpenClaw 的显式配置；这不代表此角色没有安装技能。</p>;
  return <>
    <p>以下为历史配置声明，不证明技能已安装、已加载或权限已生效。</p>
    <label className="field">查看声明记录
      <select value={selectedId} onChange={event => setSelectedId(event.target.value)} style={{ width: '100%', minWidth: 0 }}>
        {history.observations.map((o, index) => <option key={o.id} value={o.id}>
          {index === 0 ? '最近接收' : `历史 ${index}`} · {o.received_at}
        </option>)}
      </select>
    </label>
    {history.observations_truncated ? <p>仅展示最近 100 条接收记录，不是完整历史。</p> : null}
    <dl className="kv-list">
      <dt>声明来源</dt><dd>{sourceLabel[selected.selection.source]}</dd>
      <dt>安装关联</dt><dd>尚未解析，不能按同名认定归属</dd>
      <dt>有效权限</dt><dd>未由此声明确认</dd>
      <dt>来源设备</dt><dd>{selected.device.revoked ? '凭据已吊销，仅保留历史' : '凭据未吊销，不代表当前在线'}</dd>
    </dl>
    <SelectionDescription selection={selected.selection} />
    <Link to={`/agents/skills?device_id=${encodeURIComponent(selected.device.id)}`}>查看该设备采集的技能（非归属证明） →</Link>
    <details key={selected.id}>
      <summary>查看本条声明的溯源依据</summary>
      <dl className="kv-list">
        <dt>配置观察时间</dt><dd><time dateTime={selected.observed_at}>{selected.observed_at}</time></dd>
        <dt>控制面接收时间</dt><dd><time dateTime={selected.received_at}>{selected.received_at}</time></dd>
        <dt>观察 ID</dt><dd className="mono">{selected.id}</dd>
        <dt>设备 ID</dt><dd className="mono">{selected.device.id}</dd>
        <dt>任务 ID</dt><dd className="mono">{selected.task_id}</dd>
        <dt>批次摘要</dt><dd className="mono">{selected.batch_digest}</dd>
      </dl>
      <p>批次摘要关联入站校验记录，不能单凭摘要离线重验整个批次签名。</p>
      <ul>{selected.source_evidence.map(e => <li key={e.evidence_id}>
        <div>证据：<span className="mono">{e.evidence_id}</span></div>
        <div>摘要：<span className="mono">{e.content_hash}</span></div>
        <time dateTime={e.observed_at}>{e.observed_at}</time>
      </li>)}</ul>
    </details>
  </>;
}

function SelectionRequest({ assetId }: { assetId: string }) {
  const [history, setHistory] = useState<RoleSkillHistory>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let live = true;
    getRoleSkillHistory(assetId).then(value => { if (live) setHistory(value); })
      .catch(reason => { if (live) setError(reason instanceof ApiError && reason.status === 403
        ? '当前账号无权读取技能声明及环境来源，请联系组织管理员。'
        : '技能声明读取失败，不能据此判断没有技能。'); });
    return () => { live = false; };
  }, [assetId]);
  if (error) return <p role="alert">{error}</p>;
  return history ? <RoleSkillHistoryDetails history={history} /> : <p role="status">正在读取技能声明…</p>;
}

export default function RoleSkillSelectionPanel({ assetId }: { assetId: string }) {
  const [attempt, setAttempt] = useState(0);
  return <section className="card role-skill-panel" aria-label="角色技能声明">
    <h2>角色技能声明</h2>
    <button className="btn" onClick={() => setAttempt(n => n + 1)}>刷新技能声明</button>
    <SelectionRequest key={`${assetId}:${attempt}`} assetId={assetId} />
  </section>;
}
