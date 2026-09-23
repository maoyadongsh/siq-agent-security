import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { LocalApiError, localApi } from '../api';
import { platformLabel } from '../format';
import { validActivityFilter, type ActivityView } from '../taskActivities';
import { activityFilterNames, activityQueryParams, decisionNames, emptyActivityFilters, localDateTime, readActivityFilters,
  type ActivityQueryFilters, type ActivityQueryItem, type ActivityQueryPage } from '../activityQuery';

const knownPlatforms = ['hermes', 'openclaw', 'workbuddy', 'trae', 'openshell'];
const decisionLabels = { allow: '允许', deny: '拒绝', hold: '需批准', redact: '脱敏', other: '其他裁决' };
const columns: TableColumn<ActivityQueryItem>[] = [
  { key: 'run', header: '运行', render: (r) => <>
    <strong className="activity-nowrap">{r.binding ? `${platformLabel(r.binding.platform)} 运行` : '未归属活动'}</strong>
    <details className="activity-identifiers"><summary>查看标识</summary>
      {r.binding ? <><p>任务：<code>{r.binding.task_id}</code></p><p>智能体：<code>{r.binding.agent_id}</code></p><p>会话：<code>{r.binding.session_id}</code></p></> : <p>缺少完整可信绑定。</p>}
      <p>回执序号：{r.first_seq}–{r.last_seq}</p>
    </details>
  </> },
  { key: 'time', header: '最近记录时间', render: (r) => r.last_recorded_at ? <time dateTime={r.last_recorded_at}>{new Date(r.last_recorded_at).toLocaleString('zh-CN', { hour12: false })}</time> : '时间未记录' },
  { key: 'decisions', header: '调用裁决', render: (r) => <div className="activity-decisions">{decisionNames.some((name) => r.decisions[name] > 0)
    ? decisionNames.filter((name) => r.decisions[name] > 0).map((name) => <span key={name}>{decisionLabels[name]} {r.decisions[name]}</span>) : '无裁决记录'}</div> },
  { key: 'count', header: '回执数', render: (r) => String(r.receipt_count) },
];
export default function TaskActivitiesPage() {
  const [params, setParams] = useSearchParams();
  const view: ActivityView = params.get('view') === 'unassigned' ? 'unassigned' : 'tasks';
  const rawOffset = params.get('offset') ?? '0';
  const offset = /^(0|[1-9][0-9]{0,5})$/.test(rawOffset) ? Number(rawOffset) : 0;
  const snapshot = params.get('snapshot') || undefined;
  const filters = readActivityFilters(params);
  const filterKey = JSON.stringify(filters);
  const filtered = activityFilterNames.some((name) => filters[name] !== '');
  const [retry, setRetry] = useState(0);
  const [filterError, setFilterError] = useState('');
  const [state, setState] = useState<{ key: string; data?: ActivityQueryPage; error?: string }>({ key: '' });
  const key = JSON.stringify([view, offset, snapshot, filterKey, retry]);
  const current = state.key === key ? state : undefined;
  const loading = !current?.data && !current?.error;
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    localApi.taskActivityQuery(view, offset, filters, snapshot, controller.signal).then((data) => {
      if (active) setState({ key, data });
    }).catch((error: unknown) => {
      if (!active) return;
      const message = error instanceof LocalApiError && error.status === 409
        ? '活动记录已更新，请点击“刷新记录”重新加载。'
        : error instanceof LocalApiError && error.status === 400 ? '筛选条件无效，请核对时间范围后重新应用。'
          : '暂时无法读取可信活动记录。请确认本地服务已启动，再刷新重试。';
      setState({ key, error: message });
    });
    return () => { active = false; controller.abort(); };
  }, [view, offset, snapshot, filterKey, key]);
  const data = current?.data;
  const navigate = (next: number) => {
    if (data) setParams(activityQueryParams(view, filters, { offset: String(next), snapshot: data.snapshot }));
  };
  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = Object.fromEntries(activityFilterNames.map((name) => [name, String(form.get(name) ?? '').trim()])) as unknown as ActivityQueryFilters;
    const preset = (event.nativeEvent as SubmitEvent).submitter?.getAttribute('value');
    if (preset === '24h' || preset === '7d') {
      const now = Date.now();
      next.from = new Date(now - (preset === '24h' ? 1 : 7) * 86400000).toISOString();
      next.to = new Date(now).toISOString();
    } else {
      for (const name of ['from', 'to'] as const) {
        if (!next[name]) continue;
        const at = new Date(next[name]);
        if (!Number.isFinite(at.getTime())) { setFilterError('请输入有效的开始和结束时间。'); return; }
        next[name] = at.toISOString();
      }
    }
    if (next.from && next.to && new Date(next.from) >= new Date(next.to)) { setFilterError('开始时间必须早于结束时间。'); return; }
    if (activityFilterNames.some((name) => !validActivityFilter(next[name]))) { setFilterError('筛选条件不能包含控制字符，且每项最多 256 个字符。'); return; }
    setFilterError('');
    setParams(activityQueryParams(view, next));
  };
  return <section>
    <PageHeader kicker="本机记录" icon="audit" title="运行记录"
      description="按最近记录排列。调用裁决说明工具是否获准，业务结果请进入详情核对。"
      connection={loading ? 'loading' : current?.error ? 'disconnected' : 'connected'} connectionError={current?.error}
      actions={<button className="btn btn-primary" disabled={loading} onClick={() => { setParams(activityQueryParams(view, filters)); setRetry((v) => v + 1); }}>刷新记录</button>} />
    <div className="card">
      <div className="toolbar">
        <button className={view === 'tasks' ? 'btn btn-primary' : 'btn'} aria-pressed={view === 'tasks'} onClick={() => setParams(activityQueryParams('tasks', filters))}>已归属任务</button>
        <button className={view === 'unassigned' ? 'btn btn-primary' : 'btn'} aria-pressed={view === 'unassigned'} onClick={() => setParams(activityQueryParams('unassigned', filters))}>未归属活动</button>
      </div>
      <form key={filterKey} onSubmit={applyFilters} aria-label="筛选任务活动">
        <div className="form-row activity-filters">
          <div className="field field-flush field-grow"><label htmlFor="activity-query">关键词</label><input id="activity-query" name="q" maxLength={256} defaultValue={filters.q} placeholder="搜索任务、智能体或会话标识" /></div>
          <div className="field field-flush"><label htmlFor="activity-platform">平台</label><select id="activity-platform" name="platform" defaultValue={filters.platform}>
            <option value="">全部平台</option>{knownPlatforms.map((p) => <option key={p} value={p}>{platformLabel(p)}</option>)}
            {filters.platform && !knownPlatforms.includes(filters.platform) ? <option value={filters.platform}>{platformLabel(filters.platform)}</option> : null}
          </select></div>
          <div className="field field-flush"><label htmlFor="activity-action">调用裁决</label><select id="activity-action" name="action" defaultValue={filters.action}>
            <option value="">全部裁决</option><option value="allow">有允许调用</option><option value="deny">有拒绝调用</option><option value="hold">有需批准调用</option><option value="redact">有脱敏调用</option>
          </select></div>
        </div>
        <div className="form-row activity-filters">
          <div className="field field-flush"><label htmlFor="activity-from">记录时间从</label><input id="activity-from" name="from" type="datetime-local" step="any" defaultValue={localDateTime(filters.from)} /></div>
          <div className="field field-flush"><label htmlFor="activity-to">到（不含）</label><input id="activity-to" name="to" type="datetime-local" step="any" defaultValue={localDateTime(filters.to)} /></div>
          <div className="toolbar"><button className="btn" type="submit" value="24h">最近24小时</button><button className="btn" type="submit" value="7d">最近7天</button></div>
        </div>
        <details className="block-gap" open={!!(filters.agent_id || filters.session_id || filters.task_id)}><summary>高级筛选：精确标识</summary>
          <div className="form-row activity-filters">
            <div className="field field-flush"><label htmlFor="activity-agent">智能体</label><input id="activity-agent" name="agent_id" maxLength={256} defaultValue={filters.agent_id} /></div>
            <div className="field field-flush"><label htmlFor="activity-session">会话</label><input id="activity-session" name="session_id" maxLength={256} defaultValue={filters.session_id} /></div>
            <div className="field field-flush"><label htmlFor="activity-task">任务</label><input id="activity-task" name="task_id" maxLength={256} defaultValue={filters.task_id} /></div>
          </div>
          <p>关键词与精确标识不搜索参数原文或 Skill 内容。</p>
        </details>
        <div className="toolbar block-gap">
          <button className="btn btn-primary" type="submit">应用筛选</button>
          <button className="btn" type="button" disabled={!filtered} onClick={() => { setFilterError(''); setParams(activityQueryParams(view, emptyActivityFilters)); }}>清空筛选</button>
          {filtered ? <span role="status">已应用筛选，共 {data?.total ?? '…'} 项。</span> : null}
        </div>
        <p className="page-desc">按每次运行最后一条回执的时间筛选，使用当前浏览器时区。一次运行可同时包含多种裁决；“需批准”不表示当前仍待审批。</p>
        {filterError ? <p role="alert" className="action-error">{filterError}</p> : null}
      </form>
      {view === 'unassigned' ? <p>这些记录缺少完整的任务或主体绑定，系统不会根据时间或工具名称猜测归属。</p> : null}
      {current?.error ? <p className="action-error" role="alert">{current.error}</p> : null}
      {data?.history_integrity === 'failed' ? <p className="action-error" role="alert">历史完整性核对失败，请检查证据记录。</p> : null}
      <div className="activity-list"><SimpleTable columns={[...columns, { key: 'detail', header: '操作', render: (r) => <Link className="activity-nowrap" to={`/activities/${r.activity_id}?${activityQueryParams(view, filters, { snapshot: data?.snapshot ?? '', list_offset: String(offset) })}`}>查看活动记录</Link> }]} rows={data?.items ?? []} rowKey={(r) => r.activity_id}
        emptyText={loading ? '正在读取记录…' : current?.error ? '运行记录当前不可用。' : filtered ? '没有匹配当前筛选条件的运行记录。' : view === 'tasks' ? '尚无已归属任务，可切换查看未归属活动。' : '没有未归属活动。'} /></div>
      {data ? <div className="toolbar block-gap">
        <button className="btn" disabled={offset === 0} onClick={() => navigate(Math.max(0, offset - 50))}>上一页</button><span>共 {data.total} 项</span>
        <button className="btn" disabled={data.next_offset === null} onClick={() => { if (data.next_offset !== null) navigate(data.next_offset); }}>下一页</button>
      </div> : null}
      {data ? <details className="block-gap"><summary>记录核验与原始回执</summary><p>回执验签通过。{data.history_integrity === 'verified' ? '已核对历史完整性。' : data.history_integrity === 'failed' ? '历史完整性核对失败。' : '完整历史尚待核对。'}业务结果需单独核验。</p><Link to="/receipts">查看原始回执列表</Link></details> : null}
    </div>
  </section>;
}
