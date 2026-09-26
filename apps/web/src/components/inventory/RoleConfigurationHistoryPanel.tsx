import { Fragment, useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import { getConfigurationHistory, type ConfigurationHistoryPage, type ConfigurationSnapshot } from '@/api/roleConfigurationHistory';
import { useConsoleContext } from '@/components/ConsoleContext';
import SnapshotComparisonPanel, { type SnapshotSelection } from '@/components/role-skill-snapshot-comparison/SnapshotComparisonPanel';

export function ConfigurationHistoryDetails({ value, onCompare, comparisonOpen }: {
  value: ConfigurationHistoryPage;
  onCompare?: (row: ConfigurationSnapshot) => void;
  comparisonOpen?: boolean;
}) {
  return <>
    <p>本页 {value.items.length} 条已保存配置观察，不代表全部历史或全部扫描。配置快照不是原批重新验签证明，也不证明角色已加载技能或权限已生效。</p>
    {!value.items.length ? <p>当前页无可读配置历史；旧采集器可能未记录快照，不代表未安装智能体或技能。</p> : null}
    {value.items.map(row => <details key={row.observation_id}>
      <summary>{row.observed_at} · {row.status === 'recorded_snapshot' ? '已保存配置快照' : '配置快照不可核对'}</summary>
      <dl className="kv-list">
        <dt>观察 ID</dt><dd className="mono">{row.observation_id}</dd>
        <dt>配置观察时间</dt><dd><time dateTime={row.observed_at}>{row.observed_at}</time></dd>
        <dt>接收时间</dt><dd><time dateTime={row.received_at}>{row.received_at}</time></dd>
        <dt>环境 / 设备</dt><dd>{row.environment_id} / {row.device_id}</dd>
        <dt>设备凭据</dt><dd>{row.device_revoked ? '已吊销，仅保留历史' : '未吊销，不代表当前在线'}</dd>
        {row.configuration ? <>
          <dt>框架</dt><dd>{row.configuration.framework_source.framework === 'hermes' ? 'Hermes' : 'OpenClaw'}</dd>
          <dt>配置实例摘要</dt><dd className="mono">{row.configuration.framework_source.instance_key}</dd>
          <dt>配置内容摘要</dt><dd className="mono">{row.configuration.framework_source.config_sha256}</dd>
          <dt>配置证据 ID</dt><dd>{row.configuration.framework_source.evidence_id || '未提供'}</dd>
          <dt>采集任务 ID</dt><dd>{row.configuration.task_id}</dd>
          <dt>批次摘要</dt><dd className="mono">{row.configuration.batch_digest}</dd>
          <dt>技能目录来源</dt><dd>{row.configuration.skill_source_roots === null ? '本快照未记录，不从最新配置补填'
            : row.configuration.skill_source_roots.status === 'unresolved' ? '来源未确认，不代表未安装技能'
            : row.configuration.skill_source_roots.status === 'layout_candidate' ? '已记录 profile 本地布局候选，不涵盖外部/项目来源，不代表安装或加载'
            : '已记录两个工作区来源声明，不代表技能安装或加载'}</dd>
          {row.configuration.skill_source_roots?.roots.map(root => <Fragment key={root.kind}>
            <dt>{root.kind === 'profile_skills' ? 'Profile 本地技能布局摘要' : root.kind === 'workspace_skills' ? '工作区技能目录摘要' : '项目智能体技能目录摘要'}</dt>
            <dd className="mono">{root.locator_sha256}</dd>
          </Fragment>)}
        </> : <><dt>配置证据</dt><dd>快照结构或关联尚不可核对，不展示异常原文，也不回退最新配置。</dd></>}
      </dl>
      {onCompare ? <button type="button" className="btn" disabled={comparisonOpen} onClick={() => onCompare(row)}>与最新技能观察对照</button> : null}
    </details>)}
  </>;
}

function HistoryPage({ assetId, cursor, next, retry, onCompare, comparisonOpen }: {
  assetId: string; cursor?: string; next: (c: string) => void; retry: () => void;
  onCompare: (row: ConfigurationSnapshot) => void; comparisonOpen: boolean;
}) {
  const [value, setValue] = useState<ConfigurationHistoryPage>();
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    void getConfigurationHistory(assetId, cursor).then(v => { if (active) setValue(v); })
      .catch(e => { if (active) setError(e instanceof ApiError && e.status === 403
        ? '当前账号无权读取配置历史，请重新核对组织权限。' : '配置历史读取失败，不能据此判断没有历史。'); });
    return () => { active = false; };
  }, [assetId, cursor]);
  if (error) return <><p role="alert">{error}</p><button type="button" className="btn" onClick={retry}>重试本页配置历史</button></>;
  if (!value) return <p role="status">正在读取配置历史…</p>;
  return <><ConfigurationHistoryDetails value={value} onCompare={onCompare} comparisonOpen={comparisonOpen} />
    {value.next_cursor ? <button type="button" className="btn" onClick={() => next(value.next_cursor!)}>下一页配置历史</button> : null}</>;
}

function HistoryPanel({ assetId }: { assetId: string }) {
  const [cursors, setCursors] = useState<string[]>([]);
  const [attempt, setAttempt] = useState(0);
  const [selection, setSelection] = useState<SnapshotSelection | null>(null);
  const cursor = cursors.at(-1);
  // 历史刷新/翻页会改变可见历史，选中快照必须随之清除，避免选中项脱离当前可见历史。
  const clearSelection = () => setSelection(null);
  return <section className="card" aria-label="角色配置历史" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>角色配置历史</h2>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      <button type="button" className="btn" onClick={() => { setCursors([]); setAttempt(n => n + 1); clearSelection(); }}>刷新配置历史</button>
      <button type="button" className="btn" disabled={!cursors.length} onClick={() => { setCursors(v => v.slice(0, -1)); clearSelection(); }}>上一页配置历史</button>
    </div>
    <HistoryPage key={JSON.stringify([cursor, attempt])} assetId={assetId} cursor={cursor}
      next={c => { setCursors(v => [...v, c]); clearSelection(); }}
      retry={() => setAttempt(n => n + 1)}
      onCompare={row => setSelection({ assetId, observationId: row.observation_id, snapshot: row })}
      comparisonOpen={selection !== null} />
    {selection ? <SnapshotComparisonPanel selection={selection} onClose={clearSelection} /> : null}
  </section>;
}

export default function RoleConfigurationHistoryPanel({ assetId }: { assetId: string }) {
  const { status, data } = useConsoleContext();
  if (status !== 'ready' || !data?.access.agents || !data.access.environments) return null;
  return <HistoryPanel key={JSON.stringify([data.tenant.id, data.actor.type, data.actor.id, assetId])} assetId={assetId} />;
}
