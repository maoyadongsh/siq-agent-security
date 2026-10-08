import { useEffect, useRef, useState } from 'react';
import {
  assessBehavior, assessmentLabel, behaviorState, collectBehavior, readBehavior, readBehaviorHistory, readBehaviorProfiles,
  type BehaviorAssessment, type BehaviorOperation, type BehaviorProfile, type BehaviorScope,
} from '@/api/deploymentBehavior';
import { formatListCoverage, type ListMeta } from '@/api/listMeta';

const time = (date: string) => new Date(date).toLocaleString('zh-CN', { hour12: false });
function Scope({ value }: { value: BehaviorScope }) {
  return <dl className="behavior-scope">
    <dt>目标</dt><dd>{value.target}</dd><dt>策略版本</dt><dd>{value.policy_revision}</dd>
    <dt>受控接收端</dt><dd>{value.endpoint}</dd><dt>允许路径</dt><dd>{value.allow_path}</dd>
    <dt>拒绝路径</dt><dd>{value.deny_path}</dd><dt>覆盖范围</dt><dd>IPv4 · {value.transport === 'http_connect' ? '显式 CONNECT' : '直接 TCP'} · {value.attempts} 轮允许／拒绝及前后连通性对照</dd>
  </dl>;
}
export default function DeploymentBehaviorPanel({ deploymentId, canManage }: { deploymentId: string; canManage: boolean }) {
  const [opened, setOpened] = useState(false);
  const [rows, setRows] = useState<BehaviorOperation[]>([]);
  const [meta, setMeta] = useState<ListMeta | null>(null);
  const [profiles, setProfiles] = useState<BehaviorProfile[]>([]);
  const [selected, setSelected] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<BehaviorAssessment | null>(null);
  const [now, setNow] = useState(Date.now);
  const generation = useRef(0);
  const running = useRef(false);
  const chosen = profiles.find(p => p.profile_id === selected);
  const inFlight = rows.some(r => (r.state === 'running' || r.state === 'prepared') && now < Date.parse(r.expires_at));
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { window.clearInterval(timer); generation.current += 1; };
  }, []);

  async function load() {
    if (running.current) return;
    running.current = true; setBusy(true); setError(''); setAssessment(null); setConfirmed(false);
    const ticket = ++generation.current;
    try {
      const [history, templates] = await Promise.allSettled([readBehaviorHistory(deploymentId), readBehaviorProfiles(deploymentId)]);
      if (ticket !== generation.current) return;
      if (history.status === 'fulfilled') { setRows(history.value.rows); setMeta(history.value.meta); }
      else { setRows([]); setMeta(null); setError('暂时无法读取行为测评记录，请稍后刷新。'); }
      if (templates.status === 'fulfilled') { setProfiles(templates.value); setSelected(templates.value[0]?.profile_id ?? ''); }
      else { setProfiles([]); setSelected(''); if (canManage) setError('运维测评模板暂不可用；已有历史记录仍可查看。'); }
    } finally { if (ticket === generation.current) { running.current = false; setBusy(false); } }
  }
  function remember(value: BehaviorOperation) {
    setRows(old => [value, ...old.filter(r => r.verification_id !== value.verification_id)].slice(0, 20));
    setMeta(null); // A local insertion is not a fresh full-list coverage statement.
  }
  async function execute() {
    if (!canManage || !chosen || !confirmed || running.current || pendingId || inFlight || now >= Date.parse(chosen.expires_at)) return;
    running.current = true; setBusy(true); setError(''); setAssessment(null);
    const ticket = ++generation.current;
    const verification = 'opv-' + crypto.randomUUID().replaceAll('-', '');
    setPendingId(verification); setConfirmed(false);
    try {
      const result = await collectBehavior(deploymentId, chosen, verification);
      if (ticket === generation.current) { remember(result); setPendingId(null); }
    } catch { if (ticket === generation.current) setError('本次请求结果尚未确认。请核对原请求；超时或断连不证明未执行，不会自动重发探针。'); }
    finally { if (ticket === generation.current) { running.current = false; setBusy(false); } }
  }
  async function recover() {
    if (!pendingId || running.current) return;
    running.current = true; setBusy(true); setError('');
    const ticket = ++generation.current;
    try {
      const result = await readBehavior(deploymentId, pendingId);
      if (ticket === generation.current) { remember(result); setPendingId(null); }
    } catch { if (ticket === generation.current) setError('暂未查到可确认的原请求记录。请稍后再次核对；此操作不会重发探针。'); }
    finally { if (ticket === generation.current) { running.current = false; setBusy(false); } }
  }
  async function assess(value: BehaviorOperation) {
    if (running.current) return;
    running.current = true; setBusy(true); setError(''); setAssessment(null);
    const ticket = ++generation.current;
    try {
      const result = await assessBehavior(value);
      if (ticket === generation.current) setAssessment(result);
    } catch { if (ticket === generation.current) setError('当前目标核验失败，旧核验结果已清除。请确认连接和权限后重试。'); }
    finally { if (ticket === generation.current) { running.current = false; setBusy(false); } }
  }
  if (!opened) return <button type="button" className="btn" onClick={() => { setOpened(true); void load(); }}>查看行为测评</button>;
  return <section className="deployment-behavior" aria-label="OpenShell 行为测评">
    <h5>OpenShell 行为测评</h5>
    <p className="text-muted">历史记录说明当次观测。重新核验只读回当前目标；主动测评会发送固定模板内的受控连接。</p>
    {busy ? <p role="status">正在处理，请等待结果；不会自动重发探针。</p> : null}
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    {pendingId ? <div role="status"><p>待核对请求：{pendingId}</p><button className="btn" disabled={busy} onClick={() => void recover()}>核对本次请求</button></div> : null}
    <button type="button" className="btn" disabled={busy} onClick={() => void load()}>刷新测评记录与模板</button>
    {assessment ? <div role="status" className="behavior-assessment">
      <strong>{assessmentLabel(assessment, now)}</strong>
      <p>核验时间：{time(assessment.evaluated_at)}。该结论仅适用于核验时点与下方范围，不是持续监控保证。</p>
      {assessment.valid_until ? <p>证据窗口截至：{time(assessment.valid_until)}</p> : null}
      <Scope value={assessment.scope} />
    </div> : null}
    {!busy && !rows.length && meta ? <p>此部署暂无行为测评记录。</p> : null}
    <ul className="behavior-history">{rows.map(row => <li key={row.verification_id}>
      <strong>{behaviorState(row.state)}</strong>
      <p>发起时间：{time(row.issued_at)} · {now >= Date.parse(row.expires_at) ? '证据窗口已过期' : `证据窗口截至 ${time(row.expires_at)}`}</p>
      <details><summary>查看本次范围与标识</summary><Scope value={row.scope} /><p>记录：{row.verification_id}</p><p>观测数：{row.observation_count}</p></details>
      <button type="button" className="btn" disabled={busy || row.state !== 'accepted' || now >= Date.parse(row.expires_at)} onClick={() => void assess(row)}>重新核验当前目标</button>
    </li>)}</ul>
    {meta ? <p className="text-muted">{formatListCoverage(meta, rows.length)}</p> : null}
    {canManage ? <div className="behavior-collection">
      <h5>发起受控测评</h5>
      {!profiles.length ? <p>此部署暂无可用的运维批准模板。请联系运维配置本目标的短期测评范围。</p> : <>
        <label>运维批准模板<select value={selected} disabled={busy} onChange={e => { setSelected(e.target.value); setConfirmed(false); }}>
          {profiles.map(p => <option key={p.profile_id} value={p.profile_id}>{p.profile_id}</option>)}
        </select></label>
        {chosen ? <><Scope value={chosen.scope} /><p>模板有效期至：{time(chosen.expires_at)}。不覆盖其他路径、IPv6或重定向。</p></> : null}
        <label className="behavior-confirm"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} />我确认在上述目标和范围内执行受控连接测评。</label>
        <button type="button" className="btn btn-primary" disabled={busy || !confirmed || !chosen || !!pendingId || inFlight || now >= Date.parse(chosen.expires_at)} onClick={() => void execute()}>开始受控测评</button>
        {inFlight ? <p role="status">已有请求正在处理或等待核对，请刷新历史记录。</p> : null}
      </>}
    </div> : <p className="text-muted">当前账号可查看记录并核验目标；主动测评需要策略管理权限。</p>}
  </section>;
}
