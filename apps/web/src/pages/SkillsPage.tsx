import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ApiError } from '@/api/client';
import { getSkillInventory, type SkillInstallation } from '@/api/skillInventory';
import PageHeader from '@/components/PageHeader';
import SkillHistory from '@/components/SkillHistory';

export function SkillCard({ skill }: { skill: SkillInstallation }) {
  const o = skill.latest_observation;
  return <article className="card" style={{ overflowWrap: 'anywhere' }}>
    <h2>{o?.name ?? '尚未识别名称的技能'}</h2>
    <dl className="kv-list">
      <dt>发现环境</dt><dd>{skill.environment.name}</dd>
      <dt>采集设备</dt><dd>{skill.device.identity}{skill.device.revoked ? '（凭据已吊销，仅保留历史）' : '（不代表当前在线）'}</dd>
      <dt>角色归属</dt><dd>尚无关联证据</dd>
      <dt>声明工具权限</dt><dd>{!o || o.parse_status !== 'parsed' ? '尚未解析，权限未知'
        : !o.allowed_tools_present ? '未声明，不代表不需要权限'
        : o.declared_tools.length ? o.declared_tools.join('、') : '显式空声明，不代表运行时无权限'}</dd>
      <dt>实际生效权限</dt><dd>尚未核验</dd>
      <dt>最近观察</dt><dd>{o ? <time dateTime={o.observed_at}>{new Date(o.observed_at).toLocaleString()}</time> : '暂无观察记录'}</dd>
    </dl>
    <details><summary>查看溯源摘要</summary>
      <p>安装记录：{skill.installation_id}</p><p>位置摘要：{skill.locator_sha256}</p>
      {o ? <><p>观察记录：{o.observation_id}</p><p>解析状态：{o.parse_status}</p><p>Manifest SHA-256：{o.manifest_sha256}</p><p>批次摘要：{o.batch_digest}</p></> : null}
      <p>仅为历史静态观察，不证明当前仍安装、安全、运行时绑定或防御已生效。Manifest 摘要不是整个技能包摘要。</p>
    </details>
    <SkillHistory installationId={skill.installation_id} />
  </article>;
}

function SkillResults({ environmentId, deviceId, onRefresh }: { environmentId: string; deviceId: string; onRefresh: () => void }) {
  const [rows, setRows] = useState<SkillInstallation[]>([]);
  const [cursor, setCursor] = useState<string>();
  const [next, setNext] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState('');
  useEffect(() => {
    let live = true;
    getSkillInventory(environmentId, deviceId, cursor).then(page => {
      if (!live) return;
      setRows(previous => cursor ? [...previous, ...page.items] : page.items);
      setNext(page.next_cursor); setBusy(false);
    }).catch(reason => {
      if (!live) return;
      if (reason instanceof ApiError && (reason.status === 403 || reason.status === 401)) { setRows([]); setNext(null); }
      setBusy(false); setError(reason instanceof ApiError && reason.status === 403
        ? '当前账号缺少资产或环境读取权限，请联系管理员。' : '技能清单读取失败，不能据此判断没有技能。');
    });
    return () => { live = false; };
  }, [environmentId, deviceId, cursor, attempt]);
  const term = search.trim().toLowerCase();
  const shown = rows.filter(row => `${row.latest_observation?.name ?? ''} ${row.environment.name} ${row.device.identity}`.toLowerCase().includes(term));
  return <>
    <PageHeader icon="agents" title="技能清单" description="查看静态发现的技能与声明权限；发现不等于授权或已受保护。"
      connection={error ? 'disconnected' : busy ? 'loading' : 'connected'} connectionError={error}
      actions={<div className="row-actions"><Link className="btn" to="/agents">返回智能体资产</Link><button className="btn" onClick={onRefresh}>刷新技能清单</button></div>} />
    {environmentId || deviceId ? <p>当前限定环境／设备来源。<Link to="/agents/skills">查看全部来源</Link></p> : null}
    <label>搜索已加载的技能、环境或设备 <input value={search} onChange={event => setSearch(event.target.value)} /></label>
    {error ? <p role="alert">{error} <button className="btn" disabled={busy} onClick={() => { setError(''); setBusy(true); setAttempt(n => n + 1); }}>重试读取技能</button></p> : null}
    {busy ? <p role="status">正在读取技能观察…</p> : null}
    {rows.length > 0 ? <p>已加载 {rows.length} 条安装记录，当前显示 {shown.length} 条。{next ? '还有更多记录。' : ''}{error ? '现有记录仅供参考，本次读取未完成。' : ''}</p> : null}
    {!busy && !error && !rows.length ? <p>尚无技能观察记录。这不证明设备没有安装技能，请核对接入状态和确认的采集范围。 <Link to="/environments">查看环境与设备</Link></p> : null}
    {!busy && rows.length > 0 && !shown.length ? <p>已加载记录中没有匹配项；搜索不覆盖尚未加载的记录。</p> : null}
    {shown.map(skill => <SkillCard key={skill.installation_id} skill={skill} />)}
    {next ? <button className="btn" disabled={busy || !!error} onClick={() => { setBusy(true); setCursor(next); }}>加载更多技能</button> : null}
  </>;
}

export default function SkillsPage() {
  const [params] = useSearchParams();
  const environmentId = params.get('environment_id') ?? '';
  const deviceId = params.get('device_id') ?? '';
  const [refresh, setRefresh] = useState(0);
  return <section>
    <SkillResults key={JSON.stringify([environmentId, deviceId, refresh])} environmentId={environmentId} deviceId={deviceId} onRefresh={() => setRefresh(n => n + 1)} />
  </section>;
}
