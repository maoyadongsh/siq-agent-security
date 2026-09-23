import { useEffect, useRef, useState } from 'react';
import Modal from './Modal';
import { auditAction, deploymentStatus, executionEvidence, readChangeExecution, type ChangeExecution } from '@/api/changeExecution';
import { changeStatus } from '@/api/changeReview';
import { readDeploymentSubmission, type DeploymentSubmission } from '@/api/deploymentSubmission';

const time = (date: string) => new Date(date).toLocaleString('zh-CN', { hour12: false });
export default function ChangeExecutionDialog({ id, uncertain, expectedDeploymentId, onClose }: { id: string; uncertain?: boolean; expectedDeploymentId?: string; onClose: () => void }) {
  const [data, setData] = useState<ChangeExecution | null>(null);
  const [submission, setSubmission] = useState<DeploymentSubmission | null | undefined>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const alive = useRef(true);
  const pending = useRef(false);
  async function load(more = expanded) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setData(null); setSubmission(null); setError('');
    try {
      const [result, request] = await Promise.all([readChangeExecution(id, more), readDeploymentSubmission(id).catch(() => undefined)]);
      if (alive.current) { setData(result); setSubmission(request); setExpanded(more); }
    } catch { if (alive.current) setError('暂时无法读取部署与审计记录。请重试；若持续失败，请确认组织及访问权限。'); }
    finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, [id]);
  return <Modal open onClose={onClose} title="部署与审计" description="仅显示这份变更的记录。刷新从控制面读取历史记录，不会部署策略或重新检查执行端。" className="change-execution-dialog">
    <div className="modal-body">
      {uncertain && submission?.state !== 'recorded' ? <p role="status">上次提交结果尚未确认。请先核对下方目标、时间和审计；没有记录也不证明未执行，不要直接重复部署。</p> : null}
      {error ? <p role="alert" className="action-error">{error}</p> : null}
      {busy ? <p role="status">正在读取关联记录…</p> : null}
      {data ? <>
        {submission === undefined ? <p role="alert">部署请求状态暂时无法读取，请刷新重试。下方已有记录仍可核对。</p> : null}
        {submission ? <section aria-label="本次部署请求"><h3>本次部署请求</h3><p role="status">{submission.state === 'unconfirmed' ? '部署请求已保存，正在处理或结果待核对。请刷新查询，不要重复部署。' : submission.state === 'recorded' ? '已找回本次部署请求。执行是否生效以下方验证为准。' : '本次请求已有失败或回滚记录，请核对执行端；旧请求不会重新执行。'}</p><details><summary>请求标识</summary><p>请求：{submission.id}</p><p>部署：{submission.deployment_id}</p><p>保存时间：{time(submission.created_at)}</p></details></section> : null}
        <p>变更状态：{changeStatus(data.change_status)}。读取时间：{time(data.evaluated_at)}。</p>
        {expectedDeploymentId ? <p role="status">{data.deployments.some(d => d.id === expectedDeploymentId) ? '已从服务端独立读取本次部署记录；执行情况见下方。' : '本页尚未包含本次返回的部署标识，请查看更多或稍后刷新核对。'}</p> : null}
        <h3>部署记录</h3>
        {!data.deployments.length ? <p>尚未查询到关联部署记录。批准不代表已经部署；响应丢失时仍需核对执行端。</p> : null}
        {data.deployments.map(d => {
          const view = executionEvidence(d);
          return <article className="change-execution-record" key={d.id}>
            <h4>{d.environment_name || '环境名称未提供'} · {deploymentStatus(d.status)}</h4>
            <p>登记目标：{d.target}</p><p>记录时间：{time(d.created_at)}</p>
            <p className={`verification-badge tone-${view.tone}`}>{view.label}</p><p>{view.detail}</p>
            <p>独立读回：{{ not_checked: '没有记录', verified: '版本核对一致', mismatch: '与回执不一致', unreachable: '无法连接执行端', no_receipt: '缺少回执', unknown: '结果待核对' }[d.independent_result]}</p>
            <details><summary>记录标识与错误摘要</summary><p>部署：{d.id}</p><p>环境：{d.environment_id}</p><p>绑定：{d.binding_id || '历史记录未绑定'}</p>{d.error_digest ? <p>错误摘要：{d.error_digest}</p> : <p>无错误摘要记录。</p>}</details>
          </article>;
        })}
        <p className="text-muted">{data.deployments_truncated ? `仅显示最近 ${data.deployments.length} 次，仍有更早部署未展示。` : `本次查询返回 ${data.deployments.length} 次关联部署。`}</p>
        <h3>关联审计</h3>
        {data.audit_access === 'denied' ? <p>当前账号没有审计读取权限。请联系组织管理员授予审计查看权限；部署记录仍可查看。</p> : <>
          {!data.audit_events.length ? <p>没有查到精确关联的审计记录。历史未记录对象标识的审计无法在这里自动关联。</p> : null}
          <ol className="change-audit-list">{data.audit_events.map(e => <li key={e.id}><strong>{auditAction(e.action)}</strong><p>{time(e.created_at)} · 操作账号：{e.actor_id}</p><details><summary>查看审计标识</summary><p>记录：{e.id}</p><p>动作：{e.action}</p><p>对象：{e.resource_id}</p>{e.review_digest ? <p>审查摘要：{e.review_digest}</p> : null}{e.error_digest ? <p>错误摘要：{e.error_digest}</p> : null}</details></li>)}</ol>
          <p className="text-muted">{data.audit_truncated ? `仅显示最近 ${data.audit_events.length} 条，仍有更早审计未展示。` : `本次查询返回 ${data.audit_events.length} 条精确关联审计。`}</p>
        </>}
        {(data.deployments_truncated || data.audit_truncated) && !expanded ? <button type="button" className="btn" onClick={() => void load(true)}>查看更多关联记录</button> : null}
        {expanded && (data.deployments_truncated || data.audit_truncated) ? <p>已达到本窗口展示上限；更早记录仍保留在控制面，需通过审计与部署查询进一步核对。</p> : null}
        <details><summary>变更标识</summary><p>{data.change_id}</p></details>
      </> : null}
    </div>
    <div className="modal-actions"><button type="button" className="btn" onClick={onClose}>关闭</button><button type="button" className="btn btn-primary" disabled={busy} onClick={() => void load()}>{busy ? '正在读取…' : error ? '重试读取' : '刷新记录'}</button></div>
  </Modal>;
}
