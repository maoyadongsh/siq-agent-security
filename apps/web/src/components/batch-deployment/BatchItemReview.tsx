import { useEffect, useRef, useState } from 'react';
import type { ChangeReview } from '@/api/changeReview';
import type { DeploymentPreview } from '@/api/deploymentPreview';
import { readBatchItemReview } from './review';
import { readDeploymentImpact, type DeploymentImpact } from '@/api/deploymentImpact';
import NetworkRevokePanel from './NetworkRevokePanel';
import { useConsoleContext } from '@/components/ConsoleContext';

/** Parent keys by preview digest; neither viewing nor refreshing approves/deploys anything. */
export default function BatchItemReview({ item }: { item: DeploymentPreview }) {
  const { data: context, status: identityStatus } = useConsoleContext();
  const [review, setReview] = useState<ChangeReview | null>(null);
  const [impact, setImpact] = useState<DeploymentImpact | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);

  async function inspect() {
    if (pending.current) return;
    pending.current = true;
    const ticket = generation.current;
    setBusy(true); setError(''); setReview(null); setImpact(null);
    try {
      const [value, report] = await Promise.all([readBatchItemReview(item), readDeploymentImpact(item)]);
      if (ticket === generation.current) { setReview(value); setImpact(report); }
    } catch {
      if (ticket === generation.current) setError('无法完整核对权限内容：可能已无访问权限、变更状态或版本已变化、内容隐藏或截断。请重新核对变更；本次未执行。');
    } finally {
      if (ticket === generation.current) { pending.current = false; setBusy(false); }
    }
  }
  return <div className="batch-item-review">
    <button type="button" className="btn-sm" disabled={busy} onClick={() => void inspect()}>
      {busy ? '正在读取权限内容…' : review ? '重新读取权限与影响说明' : '查看权限与影响说明'}
    </button>
    {error ? <p role="alert">{error}</p> : null}
    {review && impact ? <>
      <p>已读取当前已批准版本的配置；这不是执行前复验，也不代表完整共享影响已确认。</p>
      <p>策略选择器和申请人填写的影响说明不等于实际共享沙箱中的全部受影响对象；尚不能据此证明单个 Skill 可独立隔离。</p>
      <dl>
        <dt>已登记资产</dt><dd>{impact.registered_subject.asset_id}</dd>
        <dt>已登记运行实例</dt><dd>{impact.registered_subject.agent_instance_id}</dd>
        <dt>覆盖范围</dt><dd>仅已登记绑定；不是完整运行时对象清单</dd>
        <dt>共享运行对象</dt><dd>未知</dd>
        <dt>单个 Skill 独立隔离</dt><dd>尚未建立证明，不能确认执行</dd>
      </dl>
      <p>审批类型：{review.approval_policy}；处理账号：{review.approver_id || '未提供'}。紧急审批仍需事后复核。</p>
      {review.sections.map(section => <details key={section.key}>
        <summary>{section.label}</summary><pre>{section.content}</pre>
      </details>)}
      <p>审阅内容摘要：<code>{review.review_digest}</code></p>
      {identityStatus === 'ready' && context?.actions.manage_policy && context.actions.propose_change && context.access.policies ? <NetworkRevokePanel key={item.policy_id} policyId={item.policy_id} /> : null}
    </> : null}
  </div>;
}
