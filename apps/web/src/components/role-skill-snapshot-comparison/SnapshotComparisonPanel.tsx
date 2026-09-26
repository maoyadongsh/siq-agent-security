import { useEffect, useRef, useState } from 'react';
import { ApiError } from '@/api/client';
import { getSnapshotComparison, type SnapshotComparisonPage } from '@/api/roleSkillSnapshotComparison';
import type { ConfigurationSnapshot } from '@/api/roleConfigurationHistory';
import './snapshot-comparison.css';

const relationshipLabel = {
  historical_source_match: '历史目录来源匹配', outside_declared_sources: '不在该快照声明的工作区来源内', unresolved: '来源未确认',
};
const rootLabel = { workspace_skills: '工作区技能目录', project_agent_skills: '项目智能体技能目录', profile_skills: 'Profile 本地技能布局候选' };
const PAGE_NOTE = '对照已保存配置与最新已记录技能观察，不是配置时刻的安装还原；目录来源匹配不代表角色已加载技能，也不代表权限已生效。';

export function SnapshotComparisonDetails({ value }: { value: SnapshotComparisonPage }) {
  const snapshot = value.configuration_observation;
  const hermes = value.schema_version === 'enterprise-role-skill-snapshot-comparison/v2';
  return <>
    <p className="role-skill-snapshot-note">{PAGE_NOTE}</p>
    {hermes ? <p>仅对照 Hermes profile 本地布局候选，不涵盖外部目录、受信任项目来源或加载优先级。</p> : null}
    <dl className="kv-list role-skill-snapshot-kv">
      <dt>选中配置观察</dt><dd className="mono">{snapshot.observation_id}</dd>
      <dt>配置观察时间</dt><dd><time dateTime={snapshot.observed_at}>{snapshot.observed_at}</time></dd>
      <dt>接收时间</dt><dd><time dateTime={snapshot.received_at}>{snapshot.received_at}</time></dd>
      <dt>环境 / 设备</dt><dd>{snapshot.environment_id} / {snapshot.device_id}</dd>
      <dt>设备凭据</dt><dd>{snapshot.device_revoked ? '已吊销，仅保留历史' : '未吊销，不代表当前在线'}</dd>
      {snapshot.configuration ? <>
        <dt>采集任务 ID</dt><dd>{snapshot.configuration.task_id}</dd>
        <dt>批次摘要</dt><dd className="mono">{snapshot.configuration.batch_digest}</dd>
      </> : null}
    </dl>
    {value.status === 'snapshot_unavailable'
      ? <p role="status">该快照不可对照：已保存配置或目录来源声明尚不可核对。不回退最新配置、其他设备或其他快照，也不代表未安装技能。</p>
      : <>
        <p>本页 {value.items.length} 个安装位置，来自该快照设备各安装位置的最新已记录观察；不代表组织全量，也不代表配置时刻的安装状态。</p>
        {!value.items.length ? <p>当前页没有安装记录；不代表设备未安装技能或已完成全部扫描。</p> : null}
        <div className="role-skill-snapshot-items">
          {value.items.map(item => <details key={item.installation_id}>
            <summary>{item.observation?.name ?? '名称未确认'} · {hermes && item.relationship_status === 'outside_declared_sources'
              ? '不在该快照的 profile 本地布局候选内' : relationshipLabel[item.relationship_status]}</summary>
            <dl className="kv-list">
              <dt>安装 ID</dt><dd className="mono">{item.installation_id}</dd>
              <dt>位置摘要</dt><dd className="mono">{item.locator_sha256}</dd>
              <dt>匹配来源</dt><dd>{item.matched_sources.length ? item.matched_sources.map(r => rootLabel[r.kind]).join('、') : '无可确认的匹配；不代表该角色不可使用'}</dd>
              {item.observation ? <>
                <dt>技能观察时间</dt><dd><time dateTime={item.observation.observed_at}>{item.observation.observed_at}</time></dd>
                <dt>清单摘要</dt><dd className="mono">{item.observation.manifest_sha256}</dd>
                <dt>观察 ID</dt><dd className="mono">{item.observation.observation_id}</dd>
                <dt>签名批次摘要</dt><dd className="mono">{item.observation.batch_digest}</dd>
                <dt>声明工具</dt><dd>{item.observation.declared_tools.length ? item.observation.declared_tools.join('、') : '未提供工具声明，不代表无权限'}</dd>
              </> : <><dt>观察证据</dt><dd>缺少可核对的位置链或签名观察，不回退旧记录推断归属。</dd></>}
            </dl>
          </details>)}
        </div>
      </>}
  </>;
}

export interface SnapshotSelection { assetId: string; observationId: string; snapshot: ConfigurationSnapshot }

function ComparisonPage({ selection, onClose }: { selection: SnapshotSelection; onClose: () => void }) {
  const [pages, setPages] = useState<SnapshotComparisonPage[]>([]);
  const [cursor, setCursor] = useState<string>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const requestSeq = useRef(0);
  useEffect(() => {
    const seq = ++requestSeq.current;
    let active = true;
    void getSnapshotComparison(selection.assetId, selection.observationId, cursor).then(value => {
      if (!active || seq !== requestSeq.current) return;
      setPending(false);
      setPages(v => [...v, value]);
    }).catch(reason => {
      if (!active || seq !== requestSeq.current) return;
      setPending(false);
      setError(reason instanceof ApiError && reason.status === 403
        ? '当前账号无权读取该快照的技能对照，请重新核对组织权限。'
        : reason instanceof ApiError && reason.status === 404
          ? '该配置观察不可读取或不存在，不能据此判断跨租户记录是否存在。'
          : '快照技能对照读取失败，不能据此判断没有技能观察。');
    });
    return () => { active = false; };
  }, [selection.assetId, selection.observationId, cursor, attempt]);
  const latest = pages.at(-1);
  const hasMore = latest !== undefined && latest.next_cursor !== null && latest.next_cursor !== cursor;
  return <>
    <div className="role-skill-snapshot-head">
      <h3>与最新技能观察对照</h3>
      <button type="button" className="btn" onClick={onClose}>关闭对照</button>
    </div>
    {error ? <p role="alert">{error}</p> : !latest ? <p role="status">正在读取所选快照的技能对照…</p> : null}
    {latest ? <>
      <SnapshotComparisonDetails value={latest} />
      <p className="role-skill-snapshot-range">{pages.length > 1 ? `已加载 ${pages.length} 页` : '当前页'} · 覆盖范围：该快照设备安装记录的分页，不虚构组织总数。</p>
      {pending ? <p role="status">正在读取下一页对照…</p> : null}
      {hasMore ? <button type="button" className="btn" disabled={pending} onClick={() => { setPending(true); setCursor(latest.next_cursor!); }}>下一页对照</button> : null}
    </> : null}
    {error ? <div className="role-skill-snapshot-actions">
      <button type="button" className="btn" onClick={() => { setPending(true); setError(''); setAttempt(n => n + 1); }}>重试本页对照</button>
    </div> : null}
  </>;
}

export default function SnapshotComparisonPanel({ selection, onClose }: { selection: SnapshotSelection; onClose: () => void }) {
  return <section className="card role-skill-snapshot-panel" aria-label="快照与最新技能观察对照" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <ComparisonPage key={JSON.stringify([selection.assetId, selection.observationId])} selection={selection} onClose={onClose} />
  </section>;
}
