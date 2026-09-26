import { useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import { getRoleSkillSources, type RoleSkillSourcePage } from '@/api/roleSkillSources';
import { useConsoleContext } from '@/components/ConsoleContext';

const relationshipLabel = {
  historical_source_match: '历史目录来源匹配', outside_declared_sources: '不在本次声明的工作区来源内', unresolved: '来源未确认',
};
const rootLabel = { workspace_skills: '工作区技能目录', project_agent_skills: '项目智能体技能目录', profile_skills: 'Hermes profile 本地技能布局候选' };

export function RoleSkillSourceDetails({ value }: { value: RoleSkillSourcePage }) {
  if (value.status === 'source_unavailable') return <p>角色配置或目录来源尚不可核对，不代表未安装技能。</p>;
  const source = value.framework_source.source;
  const hermes = value.schema_version === 'enterprise-role-skill-sources-view/v2';
  return <>
    <p>{hermes ? '仅比较当前页设备安装记录与 Hermes profile 本地技能布局候选；不涵盖外部目录、受信任项目来源或实际加载。' : '仅比较当前页设备安装记录与两个已声明的工作区技能来源；不代表组织全量或全部加载来源。'}</p>
    {source ? <p>配置观察：<time dateTime={source.observed_at}>{source.observed_at}</time>。
      {source.device_revoked ? '设备凭据已吊销，仅保留历史。' : '设备未吊销，不代表当前在线。'}</p> : null}
    <p>本页 {value.items.length} 个安装位置。目录匹配不证明当前存在、角色已加载、允许列表通过或权限已生效；配置与清单观察可能不同步。</p>
    {!value.items.length ? <p>当前页没有安装记录；不代表设备未安装技能或已完成全部扫描。</p> : null}
    {value.items.map(item => <details key={item.installation_id}>
      <summary>{item.observation?.name ?? '名称未确认'} · {hermes && item.relationship_status === 'outside_declared_sources'
        ? '不在本次 profile 本地布局候选内' : relationshipLabel[item.relationship_status]}</summary>
      <dl className="kv-list">
        <dt>安装 ID</dt><dd className="mono">{item.installation_id}</dd>
        <dt>位置摘要</dt><dd className="mono">{item.locator_sha256}</dd>
        <dt>匹配来源</dt><dd>{item.matched_sources.length ? item.matched_sources.map(r => rootLabel[r.kind]).join('、') : '无可确认的匹配；不代表该角色不可使用'}</dd>
        {item.observation ? <>
          <dt>清单观察</dt><dd><time dateTime={item.observation.observed_at}>{item.observation.observed_at}</time></dd>
          <dt>清单摘要</dt><dd className="mono">{item.observation.manifest_sha256}</dd>
          <dt>观察 ID</dt><dd className="mono">{item.observation.observation_id}</dd>
          <dt>签名批次摘要</dt><dd className="mono">{item.observation.batch_digest}</dd>
          <dt>声明工具</dt><dd>{item.observation.declared_tools.length ? item.observation.declared_tools.join('、') : '未提供工具声明，不代表无权限'}</dd>
        </> : <><dt>观察证据</dt><dd>缺少可核对的位置链或签名观察，不回退旧记录推断归属。</dd></>}
      </dl>
    </details>)}
  </>;
}

function SourcePage({ assetId, cursor, next, retry }: { assetId: string; cursor?: string; next: (cursor: string) => void; retry: () => void }) {
  const [value, setValue] = useState<RoleSkillSourcePage>();
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    void getRoleSkillSources(assetId, cursor).then(result => { if (active) setValue(result); })
      .catch(reason => { if (active) setError(reason instanceof ApiError && reason.status === 403
        ? '当前账号无权读取技能来源，请重新核对组织权限。' : '技能来源读取失败，不能据此判断没有技能。'); });
    return () => { active = false; };
  }, [assetId, cursor]);
  if (error) return <><p role="alert">{error}</p><button type="button" className="btn" onClick={retry}>重试本页来源</button></>;
  if (!value) return <p role="status">正在核对技能安装来源…</p>;
  return <><RoleSkillSourceDetails value={value} />
    {value.next_cursor ? <button type="button" className="btn" onClick={() => next(value.next_cursor!)}>下一页安装来源</button> : null}</>;
}

function SourcePanel({ assetId }: { assetId: string }) {
  const [history, setHistory] = useState<string[]>([]);
  const [attempt, setAttempt] = useState(0);
  const cursor = history.at(-1);
  return <section className="card" aria-label="角色与技能安装来源" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>角色与技能安装来源</h2>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      <button type="button" className="btn" onClick={() => { setHistory([]); setAttempt(n => n + 1); }}>重新核对技能来源</button>
      <button type="button" className="btn" disabled={!history.length} onClick={() => setHistory(h => h.slice(0, -1))}>上一页安装来源</button>
    </div>
    <SourcePage key={JSON.stringify([cursor, attempt])} assetId={assetId} cursor={cursor} next={c => setHistory(h => [...h, c])} retry={() => setAttempt(n => n + 1)} />
  </section>;
}

export default function RoleSkillSourcesPanel({ assetId }: { assetId: string }) {
  const { data, status } = useConsoleContext();
  if (status !== 'ready' || !data?.access.agents || !data.access.environments) return null;
  return <SourcePanel key={JSON.stringify([data.tenant.id, data.actor.type, data.actor.id, assetId])} assetId={assetId} />;
}
