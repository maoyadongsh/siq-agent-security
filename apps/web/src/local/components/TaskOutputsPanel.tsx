import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import Modal from '@/components/Modal';
import { localApi, LocalApiError } from '../api';
import { formatBytes } from '../rawTaskContent';
import type { RawContentRecord, RawContentRecordContent } from '../rawTaskContentManagement';
import type { TaskActivityDetail } from '../taskActivities';
import type { TaskOutputs } from '../taskOutputs';
import { fileToolOutput } from '../taskOutputPresentation';

function OutputBody({ content, platform }: { content: RawContentRecordContent; platform: string }) {
  const preview = useMemo(() => fileToolOutput(platform, content.fields), [platform, content]);
  const fields = content.fields.map((field, index) => <div key={`${index}:${field.path}`}><code>{field.path}</code><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{field.value}</pre></div>);
  return <>
    {preview ? <>
      <h3>读取文件的输出</h3>
      <p>按工具返回的文本显示。</p>
      {preview.truncated ? <p role="status">工具返回的内容已截断，以下不是完整文件。</p> : null}
      <pre aria-label="文件输出文本" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{preview.text || '（工具返回的文本为空）'}</pre>
      <details><summary>查看采集字段</summary>{fields}</details>
    </> : fields}
  </>;
}

function errorText(e: unknown) {
  if (e instanceof LocalApiError) {
    if (e.status === 401 || e.status === 403) return '当前连接没有读取输出的权限，请重新核对本地管理连接。';
    if (e.status === 404) return '这条输出已不存在或不属于本次运行，请刷新输出列表。';
    if (e.status === 410) return '这条输出已超过保留期，不能再查看。';
    if (e.status === 409) return '运行记录或输出已变化，请刷新运行详情后重新选择。';
  }
  return '暂时无法核验并读取输出，请重试；不会自动重新执行任务。';
}

function OutputReader({ detail, record, close }: { detail: TaskActivityDetail; record: RawContentRecord; close: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const [content, setContent] = useState<RawContentRecordContent>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController>();
  useEffect(() => () => { pending.current?.abort(); }, []);
  async function read() {
    if (!confirmed || pending.current) return;
    const controller = new AbortController(); pending.current = controller; setBusy(true); setError(''); setContent(undefined);
    try { const result = await localApi.readTaskOutput(detail.activity, detail.snapshot, record, controller.signal); if (!controller.signal.aborted) setContent(result); }
    catch (e) { if (!controller.signal.aborted) setError(errorText(e)); }
    finally { if (!controller.signal.aborted) { pending.current = undefined; setBusy(false); setConfirmed(false); } }
  }
  return <Modal open title="查看已采集输出" onClose={close}>
    <div className="modal-body">
      <p>仅显示所选运行在授权采集期间保存的输出；不代表报告已发布或业务任务已完成。</p>
      <p>{new Date(record.created_at).toLocaleString('zh-CN')} · {formatBytes(record.plaintext_bytes)}</p>
      {error ? <p role="alert" className="action-error">{error}</p> : null}
      {content ? <div role="region" aria-label="本次运行输出正文" className="raw-content-plaintext">
        <OutputBody content={content} platform={detail.activity.binding?.platform ?? ''} />
        <p>已排除 {record.omitted_secret_count} 个凭据字段。关闭或刷新后清除页面中的正文。</p>
      </div> : <label className="confirmation-check"><input type="checkbox" disabled={busy} checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />确认在当前页面显示这条输出，关闭后清除。</label>}
    </div>
    <div className="modal-actions"><button className="btn" onClick={close}>关闭并清除</button>{!content ? <button className="btn btn-primary" disabled={!confirmed || busy} onClick={() => void read()}>{busy ? '正在读取…' : '确认查看输出'}</button> : null}</div>
  </Modal>;
}

export default function TaskOutputsPanel({ detail }: { detail: TaskActivityDetail }) {
  const [retry, setRetry] = useState(0);
  const [limit, setLimit] = useState(20);
  const [state, setState] = useState<{ detail: TaskActivityDetail; retry: number; data?: TaskOutputs; error?: string }>();
  const [selection, setSelection] = useState<{ detail: TaskActivityDetail; record: RawContentRecord; trigger: HTMLButtonElement }>();
  const current = state?.detail === detail && state.retry === retry ? state : undefined;
  useEffect(() => {
    const controller = new AbortController();
    localApi.taskOutputs(detail.activity, detail.snapshot, controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ detail, retry, data });
    }).catch(e => { if (!controller.signal.aborted) setState({ detail, retry, error: errorText(e) }); });
    return () => controller.abort();
  }, [detail, retry]);
  const data = current?.data;
  const rows = useMemo(() => [...(data?.items ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || a.record_id.localeCompare(b.record_id)), [data]);
  const selected = selection?.detail === detail ? selection : undefined;
  const close = () => { selected?.trigger.focus(); setSelection(undefined); };
  return <section className="task-security-view" aria-label="本次运行的已采集输出">
    <div className="section-heading-row"><h2>本次运行的已采集输出</h2><button className="btn" disabled={!current} onClick={() => { setSelection(undefined); setLimit(20); setRetry(n => n + 1); }}>刷新输出列表</button></div>
    <p>只列出与本次运行准确关联的输出。未开启内容保存时，无法补录此前的输出。</p>
    {!current ? <p role="status">正在读取输出目录…</p> : null}
    {current?.error ? <p role="alert" className="action-error">{current.error}</p> : null}
    {data?.status === 'disabled' ? <p>输出内容保存尚未开启。可在 <Link to="/settings">设置</Link> 中查看采集选项；启用后仍需单独授权任务。</p> : null}
    {data?.status === 'unattributed' ? <p>无法核对该运行的输出来源，不能显示任务下的其他记录。</p> : null}
    {data?.status === 'ready' ? <>
      {data.items.length === 0 ? <p>本次运行暂无可关联的已采集输出。这不表示任务没有执行或没有生成业务文件。</p> : null}
      {rows.slice(0, limit).map((record, index) => <article key={record.record_id} className="raw-content-item">
        <h3>输出 {index + 1} · {record.status === 'active' ? '可查看' : '已到期'}</h3>
        <p>{new Date(record.created_at).toLocaleString('zh-CN')} · {formatBytes(record.plaintext_bytes)} · 保留至 {new Date(record.expires_at).toLocaleString('zh-CN')}</p>
        {record.status === 'active' ? <button className="btn" onClick={e => setSelection({ detail, record, trigger: e.currentTarget })}>查看输出 {index + 1}</button> : <p>已超过保留期，正文不可读取。</p>}
      </article>)}
      {data.items.length > limit ? <button className="btn" onClick={() => setLimit(n => n + 20)}>显示更多输出（还有 {data.items.length - limit} 条）</button> : null}
    </> : null}
    {selected ? <OutputReader key={selected.record.record_id} detail={detail} record={selected.record} close={close} /> : null}
  </section>;
}
