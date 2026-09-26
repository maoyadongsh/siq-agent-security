import { useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import { getSkillHistory } from '@/api/skillHistory';
import type { SkillObservation } from '@/api/skillInventory';

function HistoryRows({ installationId }: { installationId: string }) {
  const [rows, setRows] = useState<SkillObservation[]>([]);
  const [after, setAfter] = useState<SkillObservation>();
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    getSkillHistory(installationId, after).then(page => {
      if (!live) return;
      setRows(previous => after ? [...previous, ...page.items] : page.items);
      setMore(page.next_cursor !== null); setError(''); setBusy(false);
    }).catch(reason => {
      if (!live) return;
      if (reason instanceof ApiError && [401, 403, 404].includes(reason.status)) {
        setRows([]); setMore(false);
      }
      setError('历史读取失败，不能视为没有历史记录。'); setBusy(false);
    });
    return () => { live = false; };
  }, [installationId, after, attempt]);
  return <div>
    <p>仅展示历史静态观察，不证明当前安装、角色归属或权限生效。Manifest 摘要不是完整技能包摘要。</p>
    {busy ? <p role="status">正在读取技能历史…</p> : null}
    {error ? <p role="alert">{error} {rows.length ? '已保留此前读取的历史，本次读取未完成。' : ''}
      <button className="btn" disabled={busy} onClick={() => { setBusy(true); setAttempt(n => n + 1); }}>重试技能历史</button></p> : null}
    {!busy && !error && !rows.length ? <p>尚无历史观察记录，不代表没有安装技能。</p> : null}
    {rows.length ? <p>已加载 {rows.length} 条历史观察。{more ? '还有更多历史。' : ''}翻页不是实时快照，关闭后重新展开可刷新。</p> : null}
    {rows.map(row => <section key={row.observation_id} className="card">
      <h3>{row.name ?? '未识别名称'} · <time dateTime={row.observed_at}>{new Date(row.observed_at).toLocaleString()}</time></h3>
      <p>解析状态：{row.parse_status}</p>
      <p>声明工具权限：{row.parse_status !== 'parsed' ? '尚未解析，权限未知' : !row.allowed_tools_present
        ? '未声明，不代表不需要权限' : row.declared_tools.length ? row.declared_tools.join('、') : '显式空声明，不代表运行时无权限'}</p>
      <p>观察记录：{row.observation_id}</p><p>Manifest SHA-256：{row.manifest_sha256}</p>
      <p>批次摘要：{row.batch_digest}</p><p>解析器：{row.parser_version}</p>
    </section>)}
    {more ? <button className="btn" disabled={busy || !!error} onClick={() => { setBusy(true); setAfter(rows[rows.length - 1]); }}>加载更多技能历史</button> : null}
  </div>;
}

export default function SkillHistory({ installationId }: { installationId: string }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>查看历史观察</summary>
    {open ? <HistoryRows key={installationId} installationId={installationId} /> : null}
  </details>;
}
