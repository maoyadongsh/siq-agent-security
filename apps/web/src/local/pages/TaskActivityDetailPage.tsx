import ActivitySourcesPanel from '../components/ActivitySourcesPanel';
import ActivityExportButton from '../components/ActivityExportButton';
import ActivityTraceExportButton from '../components/ActivityTraceExportButton';
import TaskSecurityViewPanel from '../components/TaskSecurityViewPanel';
import RawContentTaskPanel from '../components/RawContentTaskPanel';
import TaskOutputsPanel from '../components/TaskOutputsPanel';
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { localApi, LocalApiError } from '../api';
import { actionLabel, platformLabel } from '../format';
import { validActivityFilter, type ActivityReceipt, type ActivityView, type TaskActivityDetail } from '../taskActivities';
import { useLocalSession } from '../session';

const columns: TableColumn<ActivityReceipt>[] = [
  { key: 'seq', header: '序号', render: (r) => String(r.seq) },
  { key: 'time', header: '时间', render: (r) => r.issued_at || '未知' },
  { key: 'tool', header: '工具', render: (r) => r.tool || '未知' },
  { key: 'action', header: '裁决', render: (r) => actionLabel(r.action) },
  { key: 'reason', header: '原因', render: (r) => r.reason || '未记录' },
  { key: 'grant', header: '授权引用', render: (r) => r.matched_grant_id ?? '未记录' },
];
const offsetValue = (raw: string | null) => raw && /^(0|[1-9][0-9]{0,5})$/.test(raw) ? Number(raw) : 0;
export default function TaskActivityDetailPage() {
  const { actorId } = useLocalSession();
  const { id = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const view: ActivityView = params.get('view') === 'unassigned' ? 'unassigned' : 'tasks';
  const offset = offsetValue(params.get('offset'));
  const from = offsetValue(params.get('list_offset') ?? params.get('from'));
  const snapshot = params.get('snapshot') || undefined;
  const retainedFilters: [string, string][] = ['platform', 'agent_id', 'session_id', 'task_id', 'q', 'from', 'to', 'action'].flatMap((name): [string, string][] => {
    const value = params.get(name) ?? '';
    return value && validActivityFilter(value) && !(name === 'from' && /^[0-9]+$/.test(value)) ? [[name, value]] : [];
  });
  const detailParams = (extra: Record<string, string> = {}) => {
    const next = new URLSearchParams({ view, list_offset: String(from) });
    for (const [name, value] of retainedFilters) next.set(name, value);
    for (const [name, value] of Object.entries(extra)) next.set(name, value);
    return next;
  };
  const [retry, setRetry] = useState(0);
  const key = JSON.stringify([id, view, offset, snapshot, retry]);
  const [state, setState] = useState<{ key: string; data?: TaskActivityDetail; error?: string }>({ key: '' });
  const current = state.key === key ? state : undefined;
  const loading = !current?.data && !current?.error;
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    localApi.taskActivityDetail(id, view, offset, snapshot, controller.signal).then((data) => {
      if (active) setState({ key, data });
    }).catch((error: unknown) => {
      if (!active) return;
      const message = error instanceof LocalApiError && error.status === 409 ? '活动记录已更新，请刷新详情后重试。'
        : error instanceof LocalApiError && error.status === 404 ? '未找到该活动，请返回活动列表重新选择。'
        : '当前无法读取可信活动详情，请检查本地服务后重试。';
      setState({ key, error: message });
    });
    return () => { active = false; controller.abort(); };
  }, [id, view, offset, snapshot, key]);
  const data = current?.data;
  const binding = data?.activity.binding;
  const page = (next: number) => {
    if (data) setParams(detailParams({ offset: String(next), snapshot: data.snapshot, list_offset: String(from) }));
  };
  const back = detailParams();
  if (data?.snapshot || snapshot) back.set('snapshot', data?.snapshot ?? snapshot!);
  back.set('offset', String(data?.snapshot || snapshot ? from : 0));
  return <section>
    <PageHeader kicker="任务追溯" icon="audit" title="运行详情" description="在同一证据快照中查看业务对象、运行模式、数据去向、授权裁决与实际结果。"
      connection={loading ? 'loading' : current?.error ? 'disconnected' : 'connected'} connectionError={current?.error}
      actions={<button className="btn btn-primary" disabled={loading} onClick={() => { setParams(detailParams()); setRetry((n) => n + 1); }}>刷新详情</button>} />
    <div className="card">
      <p>{loading ? <span role="status">正在读取运行记录…</span> : <Link to={`/activities?${back}`}>返回运行记录</Link>}</p>
      {current?.error ? <p role="alert" className="action-error">{current.error}</p> : null}
      {data ? <>
        <h2>{binding ? `${platformLabel(binding.platform)} · 运行记录` : '未归属活动'}</h2>
        {binding ? <details><summary>查看任务和会话标识</summary>
          <p>任务：{binding.task_id}</p><p>智能体：{binding.agent_id}</p><p>会话：{binding.session_id}</p>
        </details> : <p>缺少完整可信绑定，不能确定任务与主体归属。</p>}
        <p role={data.history_integrity === 'failed' ? 'alert' : 'status'}>{data.history_integrity === 'verified'
          ? '调用记录已验签，并已核对历史完整性。' : data.history_integrity === 'failed'
            ? '历史完整性核对失败，请展开审计详情检查记录。' : '调用记录已验签；完整历史尚待核对。'}</p>
      </> : null}
      {data ? <TaskSecurityViewPanel detail={data} /> : null}
      {data && binding && view === 'tasks' ? <TaskOutputsPanel detail={data} /> : null}
      <details className="block-gap"><summary>查看工具调用和审计详情</summary>
      {data && binding ? <ActivityExportButton key={key} detail={data} /> : null}
      {data && binding ? <ActivityTraceExportButton key={`trace-${key}`} detail={data} /> : null}
      {data ? <ActivitySourcesPanel key={key} detail={data} /> : null}
      {data && binding ? <RawContentTaskPanel key={`raw-${key}`} taskId={binding.task_id} actorId={actorId} /> : null}
      <SimpleTable columns={columns} rows={data?.receipts ?? []} rowKey={(r) => String(r.seq)} emptyText={loading ? '正在读取详情…' : current?.error ? '详情当前不可用。' : '本页没有回执。'} />
      {data ? <div className="toolbar toolbar-end">
        <button className="btn" disabled={offset === 0} onClick={() => page(Math.max(0, offset - 50))}>上一页</button>
        <span>共 {data.total} 条回执</span>
        <button className="btn" disabled={data.next_offset === null} onClick={() => { if (data.next_offset !== null) page(data.next_offset); }}>下一页</button>
      </div> : null}
      </details>
    </div>
  </section>;
}
