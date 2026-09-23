import { useEffect, useRef, useState } from 'react';
import Modal from './Modal';
import { useConsoleContext } from './ConsoleContext';
import { ApiError } from '@/api/client';
import { blockerLabels, changeStatus, modeLabel, readChangeReview, submitChangeReview, type ChangeReview } from '@/api/changeReview';

const unconfigured = (section: ChangeReview['sections'][number]) => !section.redacted && !section.truncated && ['null', '{}', '[]', '未配置（具体默认行为由执行后端决定）'].includes(section.content.trim());

function ReviewContent({ section }: { section: ChangeReview['sections'][number] }) {
  // Only translate exact recognised shapes; additional fields remain visible in full.
  try {
    const value: unknown = JSON.parse(section.content);
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const entries = Object.entries(value);
      if (entries.length === 1 && section.key === 'impact' && entries[0][0] === 'purpose' && typeof entries[0][1] === 'string') return <p>{entries[0][1]}</p>;
      if (entries.length === 1 && section.key === 'selector' && entries[0][0] === 'agent_ids' && Array.isArray(entries[0][1]) && entries[0][1].every(x => typeof x === 'string')) return <ul>{entries[0][1].map((id: string, i: number) => <li key={i}>{id}</li>)}</ul>;
    }
  } catch { /* Bounded non-JSON explanations are rendered as text. */ }
  return <pre>{section.content}</pre>;
}

export default function ChangeReviewDialog({ id, onClose, onUpdated }: { id: string; onClose: () => void; onUpdated: () => void }) {
  const { data: context } = useConsoleContext();
  const [snapshot, setSnapshot] = useState<ChangeReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [decision, setDecision] = useState<'' | 'approve' | 'reject'>('');
  const pending = useRef(false);
  const alive = useRef(true);

  async function load(reconcile = false) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setNotice(''); setSnapshot(null); setAcknowledged(false); setDecision('');
    try {
      const result = await readChangeReview(id);
      if (!alive.current) return;
      setSnapshot(result); setUncertain(false);
      if (reconcile) {
        setNotice(result.status === 'proposed' ? '已核对：仍待审批。请重新核对内容后选择处理方式。' : `已核对当前状态：${changeStatus(result.status)}。处理账号见下方。`);
        onUpdated();
      }
    } catch { if (alive.current) setError('暂时无法读取这份变更。请重试；若持续失败，请确认组织和访问权限。'); }
    finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [id]); // key=id ensures isolated state

  async function submit() {
    if (pending.current || !snapshot || !decision || !acknowledged || uncertain) return;
    if (decision === 'approve' ? !snapshot.can_approve : !snapshot.can_reject) return;
    pending.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await submitChangeReview(snapshot, decision);
      const result = await readChangeReview(id);
      if (!alive.current) return;
      const expected = decision === 'reject' ? 'rejected' : snapshot.approval_policy === 'break_glass' ? 'emergency_applied' : 'approved';
      if (result.status !== expected || result.approver_id !== context?.actor.id) throw new Error('处理结果待核对');
      setSnapshot(result); setAcknowledged(false); setDecision('');
      setNotice(decision === 'reject' ? '已驳回，并已从服务端核对。' : '已批准，并已从服务端核对。批准后还需部署及执行验证。');
      onUpdated();
    } catch (e) {
      if (!alive.current) return;
      setUncertain(true); setAcknowledged(false);
      setError(e instanceof ApiError && e.status === 409 ? '变更内容或状态已变化，请核对最新结果并重新审查。'
        : e instanceof ApiError && e.status === 403 ? '当前账号无权执行此操作，请核对当前状态或联系组织管理员。'
          : '暂时无法确认提交结果。请先核对处理结果，避免重复提交。');
    } finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  const close = () => { if (!pending.current) onClose(); };
  return <Modal open onClose={close} title="审查变更" description="核对本次策略及处理结果。批准只完成审批，不代表策略已在智能体上生效。" className="change-review-dialog">
    <div className="modal-body">
      {busy && !snapshot ? <p role="status">正在读取变更内容…</p> : null}
      {error ? <p role="alert" className="action-error">{error}</p> : null}
      {notice ? <p role="status" className="notice">{notice}</p> : null}
      {snapshot ? <>
        <h3>{snapshot.policy_name} · 第 {snapshot.policy_version} 版</h3>
        <dl className="change-review-facts"><dt>当前状态</dt><dd>{changeStatus(snapshot.status)}</dd><dt>保护方式</dt><dd>{modeLabel(snapshot.enforcement_mode)}</dd><dt>审批类型</dt><dd>{{ standard: '标准审批', high_risk: '高风险审批', break_glass: '紧急审批（仍需事后复核）' }[snapshot.approval_policy]}</dd><dt>提出账号</dt><dd>{snapshot.proposer_id}</dd><dt>处理账号</dt><dd>{snapshot.approver_id || '尚未处理'}</dd></dl>
        <p className="text-muted">下方展示本次提交的配置；“未配置”不代表禁止或允许。目标使用策略中的技术标识，未自动推断资产名称。</p>
        {snapshot.sections.filter(s => !unconfigured(s)).map(s => <details className="change-review-section" key={s.key} open={['selector', 'impact'].includes(s.key)}><summary>{s.label}{s.redacted ? ' · 含隐藏内容' : ''}{s.truncated ? ' · 内容不完整' : ''}</summary><ReviewContent section={s} /></details>)}
        {snapshot.sections.some(unconfigured) ? <details className="change-review-section"><summary>未填写的配置与说明（{snapshot.sections.filter(unconfigured).length} 项）</summary><p>未填写不代表禁止或允许；运行时默认行为仍需部署核验。</p><ul>{snapshot.sections.filter(unconfigured).map(s => <li key={s.key}>{s.label}：未填写</li>)}</ul></details> : null}
        {snapshot.status === 'proposed' ? <div className="change-review-decision">
          {Array.from(new Set([...snapshot.approve_blockers, ...snapshot.reject_blockers])).map(reason => <p key={reason}>{blockerLabels[reason]}</p>)}
          {!uncertain && (snapshot.can_approve || snapshot.can_reject) ? <>
            <fieldset disabled={busy}><legend>处理方式</legend><label><input type="radio" name="review-decision" checked={decision === 'approve'} disabled={!snapshot.can_approve} onChange={() => { setDecision('approve'); setAcknowledged(false); }} />批准变更</label><label><input type="radio" name="review-decision" checked={decision === 'reject'} disabled={!snapshot.can_reject} onChange={() => { setDecision('reject'); setAcknowledged(false); }} />驳回变更</label></fieldset>
            {decision ? <label><input type="checkbox" checked={acknowledged} disabled={busy} onChange={e => setAcknowledged(e.target.checked)} />{decision === 'approve' ? '我已核对适用对象、权限内容与影响，确认批准此版本。' : '我确认驳回此变更；重新申请需要提出新的变更单。'}</label> : null}
          </> : null}
        </div> : null}
        <details className="change-review-section"><summary>技术详情</summary><p>变更标识：{snapshot.change_id}</p><p>审查摘要：{snapshot.review_digest}</p></details>
      </> : null}
    </div>
    <div className="modal-actions">
      <button type="button" className="btn" disabled={busy} onClick={close}>关闭</button>
      <button type="button" className="btn" disabled={busy} onClick={() => void load(uncertain)}>{uncertain ? '核对处理结果' : snapshot ? '刷新内容' : '重新读取'}</button>
      {!uncertain && decision && snapshot?.status === 'proposed' ? <button type="button" className={`btn ${decision === 'reject' ? 'btn-danger' : 'btn-primary'}`} disabled={busy || !acknowledged} onClick={() => void submit()}>{busy ? '正在提交并核对…' : decision === 'reject' ? '确认驳回' : '确认批准'}</button> : null}
    </div>
  </Modal>;
}
