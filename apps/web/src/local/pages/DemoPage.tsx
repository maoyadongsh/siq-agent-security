import { useEffect, useState, type FormEvent } from 'react';
import './demo.css';

type ProvenanceReadback = { parameter_path: string; provenance_id: string; read_at: string;
  status: 'resolved' | 'unavailable'; error_code?: string; matches_operator_contact?: boolean;
  assertion?: { source: { type: string; trust: string }; content_digest: string;
    scope: { task_id: string; session_id: string }; parents: string[]; derivation: string } };
type Action = {
  action_id: string; receipt_id: string; tool: string; skill: string;
  decision: string; reason_code: string; authority_status: string;
  d2_attempted: boolean; d3_materialized: boolean; observation: string;
  reported_success?: boolean;
  routing_recipient?: string;
  decision_trifecta?: { private_data: boolean; untrusted_input: boolean; egress: boolean } | null;
  parameter_provenance: { parameter_path: string; provenance_refs: string[] }[];
  provenance_readbacks?: ProvenanceReadback[];
  approval_status?: string; approval_reason_code?: string; approval_expires_at?: string;
  reported_process?: { process_id: number; exit_code: number; digest: string };
  effect: { evidence: { effect_evidence_id: string; effect_type: string; result: string;
    source: { independence: string }; evidence_digest: string } } | null;
};
type Task = { id: string; scenario: string; phase: string; provider: string; error_code: string | null;
  model_calls?: { operation: string; provider: string; locality: string; payload_classification: string; task_id: string;
    status: string; elapsed_ms: number; error_code: string | null }[];
  approval?: { action_id: string; receipt_id: string; tool: string; params_digest: string; params: {path: string}; expires_at: string; resolution: string | null };
  task: { goal: string; current_skill: string | null; current_step: string; status: string;
    error_code: string | null; actions: Action[]; selected_skills?: string[]; completed_skills?: string[];
    completion: { status: string; requirements: { requirement_id: string; status: string; reason_code: string; evidence_ids: string[] }[] } | null } | null;
  intent?: { intent_id: string; digest: string; allowed_tools: string[]; allowed_effects: string[] } | null;
  result: { report: { path: string; digest: string } | null; research?: {summary: string}; messages: { recipient: string; payload_digest: string }[]; limitations: string[] } | null;
};
type Snapshot = { tasks: Task[]; provider: string; scenarios: string[]; skills?: string[]; repository: string; scope: string[]; contact: string; recipient: string;
  source_sha?: string; source_dirty?: boolean | null;
  source_sensitivity?: string; hardware?: { product: string; gpu: string; model: string; local_model_status: string;
    local_inference: string; runtime: string; checked_at: string; inference_duration_ms: number | null } };
const LABELS: Record<string, string> = { normal: '正常交付', 'research-only': '只分析，不保存或发送', 'research-report': '分析并保存报告', 'mcp-attack': 'MCP 收件人注入', 'same-value': '同值不同来源', 'fake-success': '工具伪成功', conflicting: '交付内容冲突', approval: '人工审批与进程校验', trifecta: '凭据路径边界拒绝与保守会话状态' };
const TOOLS: Record<string, string> = { web_fetch: '网络请求', read_file: '读取文件', write_file: '写入报告', send_message: '交付消息', verify_report: '启动报告校验进程' };
const API = '/hackathon/v1';

function ProvenanceEvidence({ entry }: { entry: ProvenanceReadback }) {
  return <div className="demo-provenance" data-provenance={entry.assertion?.source.type ?? 'unavailable'}>
    <p><strong>{entry.parameter_path === '/recipient' ? '收件人来源' : entry.parameter_path}</strong>
      {entry.status === 'resolved' && entry.assertion ? <>：{entry.assertion.source.type} · {entry.assertion.source.trust.toUpperCase()}</> : '：读回不可用'}</p>
    {entry.matches_operator_contact !== undefined ? <p>{entry.matches_operator_contact ? '值与受信联系人相同' : '值与受信联系人不同'}；来源资格以 SIQ 裁决为准。</p> : null}
    {entry.assertion ? <dl><dt>来源摘要</dt><dd className="demo-mono">{entry.assertion.content_digest}</dd>
      <dt>来源任务</dt><dd className="demo-mono">{entry.assertion.scope.task_id}</dd>
      <dt>来源会话</dt><dd className="demo-mono">{entry.assertion.scope.session_id}</dd>
      <dt>派生关系</dt><dd className="demo-mono">{entry.assertion.derivation} · {entry.assertion.parents.join(', ') || '直接来源'}</dd></dl> : <p>{entry.error_code}</p>}
    <p className="demo-note">SIQ 来源读回：{new Date(entry.read_at).toLocaleTimeString()}。该记录描述当时来源，不替代执行前授权。</p>
  </div>;
}

async function post(path: string, body: object, requestId?: string) {
  const response = await fetch(API + path, { method: 'POST', headers: {
    'Content-Type': 'application/json', 'X-SIQ-Demo': '1', ...(requestId ? { 'Idempotency-Key': requestId } : {}),
  }, body: JSON.stringify(body) });
  const result = await response.json() as { id?: string; error?: string };
  if (!response.ok) throw new Error(result.error ?? `HTTP ${response.status}`);
  return result;
}

export default function DemoPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [selected, setSelected] = useState('');
  const [paired, setPaired] = useState(false);
  const [code, setCode] = useState('');
  const [prompt, setPrompt] = useState('分析当前仓库代码，生成安全审查报告，并发送给 Alice。');
  const [scenario, setScenario] = useState('normal');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await fetch(API + '/tasks', { signal: controller.signal });
        if (response.status === 401) { setPaired(false); setSnapshot(null); setPollError(null); return; }
        if (!response.ok) throw new Error(`任务服务不可达（HTTP ${response.status}）`);
        setSnapshot(await response.json() as Snapshot);
        setPaired(true);
        setPollError(null);
      } catch (err) {
        if (!controller.signal.aborted) setPollError(err instanceof Error ? err.message : '任务状态读取失败');
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 800);
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);

  const tasks = snapshot?.tasks ?? [];
  const current = tasks.find(t => t.id === selected) ?? tasks[tasks.length - 1];
  const active = tasks.some(t => t.phase !== 'finished' && t.phase !== 'failed');
  const task = current?.task;
  const completion = task?.completion;
  const deliveryEvidence = completion?.requirements.find(requirement => requirement.requirement_id === 'delivery');
  const hardware = snapshot?.hardware;
  const deliveryAction = task?.actions.find(a => a.tool === 'send_message');
  const trustedDelivery = tasks.flatMap(t => t.task?.actions ?? []).find(a =>
    a.tool === 'send_message' && a.decision === 'allow' && a.routing_recipient === deliveryAction?.routing_recipient &&
    a.provenance_readbacks?.some(p => p.assertion?.source.type === 'TRUSTED_DATABASE'));

  async function pair(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try { await post('/pair', { code }); setCode(''); setPaired(true); }
    catch (err) { setError(err instanceof Error ? err.message : '配对失败'); }
    finally { setBusy(false); }
  }
  async function run(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const response = await post('/tasks', { scenario, prompt }, crypto.randomUUID().replaceAll('-', ''));
      setSelected(response.id ?? '');
    } catch (err) { setError(err instanceof Error ? err.message : '任务提交失败'); }
    finally { setBusy(false); }
  }
  async function approve(allow: boolean) {
    if (!current?.approval) return;
    setBusy(true); setError(null);
    try { await post(`/tasks/${current.id}/approval`, { action_id: current.approval.action_id, approve: allow }); }
    catch (err) { setError(err instanceof Error ? err.message : '审批提交失败'); }
    finally { setBusy(false); }
  }

  return <main className="demo-shell">
    <header className="demo-header"><div><p className="demo-kicker">SIQ AGENT SECURITY · DGX SPARK</p>
      <h1>Secure Research & Delivery</h1><p>Agent 完成任务，SIQ 验证授权与实际效果。</p></div>
      <span className="demo-provider">{snapshot?.provider === 'fixture' ? '测试模型 · 无真实推理' : snapshot?.provider ?? '等待连接'}</span></header>
    {error || pollError ? <p role="alert" className="demo-error">{error ?? pollError}。状态以最近一次读回为准。</p> : null}
    {!paired ? <section className="demo-panel"><h2>连接演示服务</h2><p>输入本次启动时显示的演示配对码。配对码五分钟内有效且只能使用一次。</p>
      <p>需要重新连接时，在本机运行 <code>./scripts/hackathon/pair.sh</code> 获取新码。</p>
      <form onSubmit={pair} className="demo-controls"><label>配对码<input autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} required /></label>
        <button disabled={busy} type="submit">{busy ? '连接中…' : '连接'}</button></form></section> : <>
      <form onSubmit={run} className="demo-controls demo-panel">
        <label className="demo-grow">任务目标<input value={prompt} onChange={e => setPrompt(e.target.value)} maxLength={4096} required /></label>
        <label>场景<select aria-label="场景" value={scenario} onChange={e => {
          setScenario(e.target.value);
          setPrompt(e.target.value === 'research-only' ? '只分析这个仓库，不保存报告，不要发出去。' : e.target.value === 'research-report'
            ? '分析这个仓库并保存安全报告，不要发送。' : '分析当前仓库代码，生成安全审查报告，并发送给 Alice。');
        }}>{(snapshot?.scenarios ?? ['normal']).map(s => <option key={s} value={s}>{LABELS[s] ?? s}</option>)}</select></label>
        <button type="submit" disabled={busy || active || Boolean(pollError)}>{active ? '任务运行中…' : busy ? '提交中…' : '开始任务'}</button>
        {tasks.length ? <label>查看任务<select aria-label="查看任务" value={current?.id ?? ''} onChange={e => setSelected(e.target.value)}>{tasks.map(t => <option key={t.id} value={t.id}>{LABELS[t.scenario]} · {t.task?.status ?? t.phase} · {t.id.slice(0, 6)}</option>)}</select></label> : null}
      </form>
      <div className="demo-grid">
        <section className="demo-panel"><p className="demo-kicker">CURRENT TASK</p><h2>{task?.goal ?? '等待提交任务'}</h2>
          <dl><dt>仓库 / 范围</dt><dd>{snapshot?.repository} / {snapshot?.scope.join(', ')}</dd>
            <dt>任务 ID</dt><dd className="demo-mono">{current?.id ?? '—'}</dd>
            <dt>Source SHA</dt><dd className="demo-mono">{snapshot?.source_sha ?? 'UNVERIFIED'}{snapshot?.source_dirty ? ' · uncommitted changes' : ''}</dd>
            <dt>敏感等级</dt><dd>{snapshot?.source_sensitivity ?? 'UNVERIFIED'}</dd>
            <dt>当前 Skill</dt><dd>{task?.current_skill ?? '—'}</dd><dt>当前步骤</dt><dd>{task?.current_step ?? current?.phase ?? '—'}</dd>
            <dt>任务状态</dt><dd><span className="demo-status" data-state={task?.status}>{task?.status ?? current?.phase ?? 'idle'}</span></dd></dl>
          {task?.error_code || current?.error_code ? <p className="demo-error">{task?.error_code ?? current?.error_code}</p> : null}
          {current?.model_calls?.length ? <div className="demo-models" aria-label="模型调用位置">{current.model_calls.map((call, index) =>
            <p key={`${call.operation}-${index}`}><strong>{call.locality === 'remote' ? 'REMOTE' : call.locality === 'local_dgx' ? 'LOCAL · DGX Spark' : 'UNVERIFIED'} · {call.provider}</strong><br />
              {call.operation === 'research' && call.locality === 'local_dgx' ? 'LOCAL ANALYSIS' : call.operation} · {call.payload_classification} · {call.status} · {(call.elapsed_ms / 1000).toFixed(2)} 秒{call.error_code ? ` · ${call.error_code}` : ''}</p>)}</div> : null}
          <aside className="demo-hardware" aria-label="DGX 硬件状态"><strong>{hardware?.product ?? 'DGX · UNVERIFIED'}</strong>
            <dl><dt>GPU</dt><dd>{hardware?.gpu ?? 'UNVERIFIED'}</dd><dt>Local Model</dt><dd>{hardware?.model ?? 'UNVERIFIED'}</dd>
              <dt>Model Endpoint</dt><dd>{hardware?.local_model_status ?? 'UNVERIFIED'}</dd>
              <dt>Local Inference</dt><dd>{hardware?.local_inference ?? 'UNVERIFIED'}</dd>
              <dt>SIQ Runtime</dt><dd>{hardware?.runtime ?? 'UNVERIFIED'}</dd></dl>
            {hardware?.local_model_status === 'UNAVAILABLE' || task?.error_code === 'dgx_local_model_unavailable' ? <p className="demo-error">DGX LOCAL MODEL UNAVAILABLE</p> : null}
            {hardware ? <p className="demo-note">探测于 {new Date(hardware.checked_at).toLocaleTimeString()} · 模型可达与实际推理分别验证。</p> : null}
          </aside>
          {current?.approval && task?.status === 'waiting_approval' ? <div className="demo-approval">
            <h3>审批本次报告校验</h3><p>启动固定校验进程，读取以下报告并核对摘要。</p>
            <p className="demo-mono">{current.approval.params.path}</p><p className="demo-mono">参数 SHA256: {current.approval.params_digest}</p>
            <p>有效期至 {new Date(current.approval.expires_at).toLocaleTimeString()}。批准后 SIQ 仍会重查原动作的参数和当前授权。</p>
            {current.approval.resolution ? <p>已提交：{current.approval.resolution}，等待执行前重查。</p> : <div className="demo-controls">
              <button type="button" disabled={busy || Boolean(pollError)} onClick={() => void approve(true)}>批准本次校验</button>
              <button type="button" disabled={busy || Boolean(pollError)} onClick={() => void approve(false)}>拒绝本次校验</button>
            </div>}
          </div> : null}
        </section>
        <section className="demo-panel"><p className="demo-kicker">AGENT SKILLS</p><h2>Agent 选择的执行计划</h2>
          {task?.selected_skills?.length ? <ol className="demo-skill-plan" aria-label="Selected Skills">{task.selected_skills.map(skill =>
            <li key={skill} data-selected-skill={skill}><span>{task.completed_skills?.includes(skill) ? '✓' : task.current_skill === skill ? '→' : '○'}</span><strong>{skill}</strong></li>)}</ol>
            : <p>等待模型从受信 Registry 中选择 Skills。</p>}
          {task?.selected_skills?.length ? <p className="demo-note">未选择：{snapshot?.skills?.filter(s => !task.selected_skills?.includes(s)).join(' · ') || '无'}</p> : null}
          <details><summary>TRUSTED INTENT · 任务授权</summary>{current?.intent ? <dl><dt>Intent</dt><dd className="demo-mono">{current.intent.intent_id}</dd>
            <dt>任务 Skills</dt><dd>{task?.selected_skills?.join(' · ') ?? '—'}</dd>
            <dt>工具</dt><dd>{current.intent.allowed_tools.join(' · ')}</dd><dt>效果</dt><dd>{current.intent.allowed_effects.join(' · ')}</dd>
            <dt>受信收件人</dt><dd>{snapshot?.contact} · {snapshot?.recipient}</dd><dt>来源要求</dt><dd>V3 必需参数来源校验；MCP 返回值不具有受信目录权限。</dd>
            <dt>摘要</dt><dd className="demo-mono">{current.intent.digest}</dd></dl> : <p>准备阶段仅允许读取；报告内容确定后签发执行 Intent。</p>}</details>
        </section>
        <section className="demo-panel demo-wide"><p className="demo-kicker">SECURITY DECISIONS</p><h2>执行时间线</h2>
          {current?.scenario === 'same-value' && trustedDelivery && deliveryAction ? <div className="demo-provenance" data-comparison="same-value">
            <strong>Value · {deliveryAction.routing_recipient}</strong><p>Trusted Directory → {trustedDelivery.decision.toUpperCase()} · MCP → {deliveryAction.decision.toUpperCase()}</p>
            <p className="demo-note">比较已记录动作的实际裁决；值相同，来源不同。</p></div> : null}
          {current?.scenario === 'trifecta' ? <p>操作员场景尝试读取凭据路径上的受控机密样例：SIQ 在边界拒绝，工具未执行、无内容被读取或离开；该次拒绝尝试仍把会话保守标记为接触过私有数据。执行会话在依赖该读取的后续步骤（含其网络请求）开始前停止，报告与交付保持未完成；准备阶段的授权内只读检索已在更早的独立会话完成。引擎级「私有数据 + 不可信输入 + 出网」拒绝由 Go 测试与历史证据另行锁定。</p> : null}
          {task?.actions.length ? <ol className="demo-actions">{task.actions.map(action => <li key={action.action_id}>
            <div><strong>{TOOLS[action.tool] ?? action.tool}</strong><span className="demo-status" data-state={action.decision}>{action.decision.toUpperCase()}</span><span>{action.skill}</span></div>
            <p>{action.reason_code}{action.decision === 'hold' ? ' · 等待操作员审批' : ''} · Authority: {action.authority_status}</p>
            {action.routing_recipient ? <p>Recipient · <strong>{action.routing_recipient}</strong></p> : null}
            {current?.scenario === 'trifecta' && action.decision_trifecta ? <p data-trifecta="decision">SIQ 决策时状态：机密数据 {String(action.decision_trifecta.private_data)} · 不可信输入 {String(action.decision_trifecta.untrusted_input)} · 出网 {String(action.decision_trifecta.egress)}</p> : null}
            {action.approval_status ? <p>审批重查：{action.approval_status} · {action.approval_reason_code}</p> : null}
            {action.provenance_readbacks?.filter(p => p.parameter_path === '/recipient').map(p => <ProvenanceEvidence key={p.provenance_id} entry={p} />)}
            <details><summary>来源与效果证据</summary><p className="demo-mono">Receipt: {action.receipt_id}</p>
              {action.parameter_provenance.map(p => <p key={p.parameter_path} className="demo-mono">{p.parameter_path} → {p.provenance_refs.join(', ')}</p>)}
              {action.provenance_readbacks?.filter(p => p.parameter_path !== '/recipient').map(p => <ProvenanceEvidence key={`${p.parameter_path}-${p.provenance_id}`} entry={p} />)}
              {action.effect ? <p className="demo-mono">{action.effect.evidence.effect_evidence_id} · {action.effect.evidence.result} · {action.effect.evidence.source.independence}</p> : <p>尚无独立效果证据。</p>}
              {action.reported_process ? <p className="demo-mono">REPORTED process {action.reported_process.process_id} · exit {action.reported_process.exit_code} · SHA256 {action.reported_process.digest}</p> : null}
            </details></li>)}</ol> : <p>提交后显示实际 SIQ 决策；工具返回成功不会自动变成 VERIFIED。</p>}
        </section>
        <section className="demo-panel demo-wide"><p className="demo-kicker">EFFECT / COMPLETION</p><h2>实际完成了什么</h2>
          {deliveryAction ? <div className="demo-effect-summary"><p>TOOL REPORTED <strong>{deliveryAction.reported_success === true ? 'success' : deliveryAction.reported_success === false ? 'failure' : 'UNKNOWN'}</strong></p>
            <p>EFFECT EVIDENCE <strong>{deliveryEvidence?.evidence_ids.length ? deliveryEvidence.status : 'missing'}</strong></p><p>COMPLETION <strong>{completion?.status.toUpperCase() ?? 'UNKNOWN'}</strong></p></div> : null}
          <p>SIQ 完成状态：<span className="demo-status" data-state={completion?.status}>{completion?.status?.toUpperCase() ?? 'UNKNOWN'}</span></p>
          {completion?.requirements.map(r => <div key={r.requirement_id} className="demo-requirement"><strong>{r.requirement_id}</strong><span className="demo-status" data-state={r.status}>{r.status}</span><span>{r.reason_code}</span><p className="demo-mono">{r.evidence_ids.join(', ') || '尚无证据'}</p></div>)}
          {current?.result ? <><p>受控接收端实际消息：{current.result.messages.length}</p>{current.result.report ? <p className="demo-mono">报告 SHA256: {current.result.report.digest}</p> : <p>研究已完成；未请求报告或交付效果，UNKNOWN 不代表已验证交付。</p>}
            {current.result.research ? <p>{current.result.research.summary}</p> : null}
            <details><summary>查看本次任务记录</summary><pre>{JSON.stringify(current.result, null, 2)}</pre></details></> : null}
          <p className="demo-note">验证范围为已承诺的报告文件与受控 HTTP 接收端。同机测试 oracle 不代表独立管理的生产证明；演示不发送外部邮件。</p>
        </section>
      </div>
    </>}
  </main>;
}
