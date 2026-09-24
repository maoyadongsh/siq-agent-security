import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import CandidateReview from '@/components/inventory/CandidateReview';
import { useApiList } from '@/hooks/useApiList';
import { assetStatusLabel, inventoryAccess, inventoryStamp, type InventoryAccess } from '@/api/inventoryReview';
import type { AgentAsset } from '@/api/types';

const empty: AgentAsset[] = [];
const sourceLabels: Record<string, string> = { hermes_profile: 'Hermes 角色配置', openclaw_config: 'OpenClaw 配置', openclaw_agent: 'OpenClaw 角色配置', docker: '容器配置', process_list: '进程信息' };
export default function AgentsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('view') === 'candidates' ? 'candidates' : 'agents';
  const agents = useApiList<AgentAsset>('/agents', empty);
  const candidates = useApiList<AgentAsset>('/candidates', empty);
  const [access, setAccess] = useState<InventoryAccess>();
  const [accessError, setAccessError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [message, setMessage] = useState('');
  const [target, setTarget] = useState<{ asset: AgentAsset; action: 'confirm' | 'dismiss' }>();
  const active = tab === 'candidates' ? candidates : agents;
  useEffect(() => {
    let live = true;
    inventoryAccess().then(v => { if (live) { setAccess(v); setAccessError(false); } })
      .catch(() => { if (live) { setAccess(undefined); setAccessError(true); } });
    return () => { live = false; };
  }, [retry]);
  const refresh = () => { agents.refresh(); candidates.refresh(); setAccess(undefined); setRetry(n => n + 1); setMessage(''); };
  const resolved = (asset: AgentAsset, reconciled: boolean) => {
    setTarget(undefined);
    setMessage(reconciled ? `已核对“${asset.name}”当前为${assetStatusLabel(asset.status)}。这可能包含其他操作者的处理，请按详情核查。`
      : `已读回“${asset.name}”：${assetStatusLabel(asset.status)}。${asset.status === 'confirmed' ? '工具权限没有因此改变。' : '原配置保持不变。'}`);
    if (['confirmed', 'managed', 'stale', 'retired'].includes(asset.status)) setParams({ view: 'agents' });
    agents.refresh(); candidates.refresh();
  };
  const columns: TableColumn<AgentAsset>[] = [
    { key: 'name', header: '名称', render: a => <Link to={`/agents/${encodeURIComponent(a.id)}?view=${tab}`}>{a.name}</Link> },
    { key: 'role', header: '业务用途', render: a => a.role || '未填写' },
    { key: 'framework', header: '框架', render: a => a.framework === 'unknown' ? '尚未识别' : a.framework },
    { key: 'status', header: '状态', render: a => assetStatusLabel(a.status) },
    { key: 'source', header: '发现来源', render: a => sourceLabels[a.source_type ?? ''] ?? '其他采集来源' },
    { key: 'updated', header: '更新时间', render: a => inventoryStamp(a.updated_at) },
  ];
  if (tab === 'candidates' && access?.can_confirm) columns.push({ key: 'actions', header: '操作', render: a => <span className="row-actions">
    <button className="btn btn-sm" disabled={active.status !== 'connected' || !!target} onClick={() => setTarget({ asset: a, action: 'confirm' })}>确认资产</button>
    <button className="btn btn-sm" disabled={active.status !== 'connected' || !!target} onClick={() => setTarget({ asset: a, action: 'dismiss' })}>驳回</button>
  </span> });
  const shownRows = active.status === 'connected' ? active.rows : [];
  return <section>
    <PageHeader icon="agents" title="智能体资产" description="先核对发现的配置与业务用途，再确认资产。确认资产不代表权限已经生效。"
      connection={active.status} connectionError={active.error} actions={<div className="row-actions">
        {access?.can_discover ? <Link className="btn" to="/environments">接入环境与发现</Link> : null}
        <button className="btn" onClick={refresh}>刷新资产列表</button>
      </div>} />
    <div className="tabs" role="tablist" aria-label="资产视图">
      <button role="tab" aria-selected={tab === 'agents'} className={`tab-btn${tab === 'agents' ? ' active' : ''}`} onClick={() => setParams({ view: 'agents' })}>资产清单{agents.status === 'connected' ? `（已加载 ${agents.rows.length}）` : ''}</button>
      <button role="tab" aria-selected={tab === 'candidates'} className={`tab-btn${tab === 'candidates' ? ' active' : ''}`} onClick={() => setParams({ view: 'candidates' })}>发现候选{candidates.status === 'connected' ? `（已加载 ${candidates.rows.length}）` : ''}</button>
    </div>
    {message ? <p role="status">{message}</p> : null}
    {accessError ? <p role="alert">无法核对操作权限，请刷新资产列表重试。</p> : null}
    {tab === 'candidates' && access && !access.can_confirm ? <p>当前账号仅可查看候选。处理候选需要资产确认权限，请联系组织管理员申请。</p> : null}
    {active.status === 'disconnected' ? <DisconnectedNotice error={active.error} onRetry={refresh} /> : null}
    {active.coverageText ? <p role="status">{active.coverageText}</p> : null}
    {shownRows.length ? <>
      <div className="inventory-desktop"><SimpleTable columns={columns} rows={shownRows} rowKey={a => a.id} /></div>
      <div className="inventory-mobile">{shownRows.map(asset => <article className="card" key={asset.id}>
        <h2>{columns[0].render(asset)}</h2>
        <dl className="kv-list">{columns.slice(1).map(column => <div className="inventory-field" key={column.key}><dt>{column.header}</dt><dd>{column.render(asset)}</dd></div>)}</dl>
      </article>)}</div>
    </> : <SimpleTable columns={columns} rows={[]} rowKey={(a: AgentAsset) => a.id}
      emptyText={active.status === 'loading' ? '正在读取资产…' : active.status === 'disconnected' ? '当前无法读取资产。' : tab === 'candidates' ? '暂无待处理候选。可从环境与设备页面提交发现任务。' : '暂无已确认资产。请在发现候选中核对后确认。'} />}
    {active.hasMore ? <div className="list-more"><button className="btn" disabled={active.loadingMore || active.status !== 'connected'} onClick={active.loadMore}>{active.loadingMore ? '正在加载…' : '加载更多'}</button></div> : null}
    {active.error && active.status === 'connected' ? <p role="alert">{active.error}</p> : null}
    {target && access?.can_confirm ? <CandidateReview key={`${target.asset.id}:${target.action}`} asset={target.asset} action={target.action} onClose={() => setTarget(undefined)} onResolved={resolved} /> : null}
  </section>;
}
