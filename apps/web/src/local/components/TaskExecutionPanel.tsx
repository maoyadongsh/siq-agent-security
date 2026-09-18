import { useEffect, useRef, useState } from 'react';
import { localApi } from '../api';
import { useLoadGuard } from '../staleGuard';
import {
  taskExecutionCandidate,
  taskExecutionIntentLines,
  taskExecutionIsTerminal,
  taskExecutionLinkage,
  taskExecutionRedactionNote,
  taskExecutionStateLabel,
  taskExecutionStopBoundary,
  taskExecutionUnresolvedGuidance,
  type TaskReadOutcome,
} from '../taskExecutions';
import type { Confirmation } from '../types';

/**
 * 一次命令执行（`exec`）的详情：执行前要看的意图，加上执行后的后端真实状态。
 * 嵌在既有确认详情里，不新建工作台。
 *
 * 三条纪律写在这个组件里：
 *  1. 屏幕上出现的每一个状态都直接来自后端投影。连接失败、"不是任务执行"、
 *     响应不可识别都被明确说成"没有取得状态"，而不是退化成某个看起来合理的状态。
 *  2. 这个面板是只读的。它没有停止按钮，因为控制台持管理会话而停止要求决策凭据；
 *     它也没有"重新执行"按钮，因为预留只有一次。
 *  3. 配对身份、连接或当前操作员变化时，旧响应立即失效——由 useLoadGuard 保证，
 *     而不是靠用户手动刷新。
 *
 * 意图部分对任何 `exec` 确认都显示（批准前就该看到目标、动作、新增权限和副作用）；
 * 后端状态部分只在存在预留时读取——没有预留就没有任务，读取也无从谈起。
 */
export default function TaskExecutionPanel({ item }: { item: Confirmation }) {
  const candidate = taskExecutionCandidate(item);
  const guard = useLoadGuard();
  const [outcome, setOutcome] = useState<TaskReadOutcome | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  // 确认项对象在每轮轮询后都是新实例，所以效果只依赖绑定标识，最新的对象经 ref 读取。
  // 这个同步效果声明在读取效果之前，同一次提交里先跑，读取时拿到的总是本轮的对象。
  const latest = useRef(item);
  useEffect(() => {
    latest.current = item;
  });

  // 只依赖绑定本身的标识：用对象本身做依赖会在每轮轮询后重复读取。
  const reservationReceiptId = item.reservation_receipt_id;
  const actionId = item.action_id;
  const decisionHash = item.decision_hash;

  useEffect(() => {
    if (!candidate) {
      setOutcome(null);
      setLoading(false);
      return;
    }
    const target = latest.current;
    let alive = true;
    setLoading(true);
    // guard 在配对身份、连接或当前操作员变化时换新实例，本效果随之重跑；
    // 旧实例的响应会拿到 undefined，既不会写入状态也不会写入错误。
    void guard(() => localApi.readTaskExecution(target)).then(
      (result) => {
        if (!alive || result === undefined) return;
        setOutcome(result);
        setLoading(false);
      },
      () => {
        if (!alive) return;
        setOutcome({ kind: 'error', status: 0 });
        setLoading(false);
      },
    );
    return () => {
      alive = false;
    };
  }, [guard, candidate, reservationReceiptId, actionId, decisionHash, refreshKey]);

  if (item.tool !== 'exec') return null;

  return <div className="block-gap" aria-busy={loading}>
    <h3>命令执行详情</h3>
    <TaskExecutionIntent item={item} expanded={candidate && outcome?.kind === 'view' && !taskExecutionIsTerminal(outcome.view)} />
    {!candidate && <p className="notice" role="status">
      此请求尚未预留执行，因此没有可读取的任务状态。批准只记录本次操作，不等于命令已执行。
    </p>}
    {candidate && <>
      <p className="page-desc">
        以下状态来自后端签名账本，与"策略已应用"分开记账；读取不会执行、停止或重放任何东西。
      </p>
      {loading && <p role="status">正在向后端核对执行状态…</p>}
      {!loading && outcome && <TaskExecutionOutcome outcome={outcome} />}
      <div className="toolbar">
        <button type="button" className="btn btn-sm" disabled={loading} onClick={() => setRefreshKey((key) => key + 1)}>
          重新读取后端状态
        </button>
      </div>
    </>}
  </div>;
}

/** 执行前需要用户看到的五件事，全部来自已批准的确认项，不来自模型输出。 */
function TaskExecutionIntent({ item, expanded }: { item: Confirmation; expanded: boolean }) {
  return <details open={expanded}>
    <summary>本次批准的目标、动作与预期副作用</summary>
    <dl>
      {taskExecutionIntentLines(item).map((line) => <IntentRow key={line.label} label={line.label} value={line.value} />)}
    </dl>
    <p className="page-desc">原始命令与原始输出默认只以摘要保存；此处不展示未脱敏内容。</p>
  </details>;
}

function IntentRow({ label, value }: { label: string; value: string }) {
  return <><dt>{label}</dt><dd className="resource-cell">{value}</dd></>;
}

function TaskExecutionOutcome({ outcome }: { outcome: TaskReadOutcome }) {
  switch (outcome.kind) {
    case 'not_a_task_execution':
      return <p className="notice" role="status">
        后端账本中没有与本次预留对应的任务执行记录。这可能不是一次 OpenShell 任务执行；未据此推断任何执行状态。
      </p>;
    case 'invalid_response':
      return <p className="action-error" role="alert">
        后端响应不符合任务执行契约，已拒绝该响应。请更新本地服务后重试；在此之前不显示任何执行状态。
      </p>;
    case 'unauthenticated':
      return <p className="action-error" role="alert">
        管理会话已失效，未能读取任务状态。请在连接恢复并重新配对后再核对。
      </p>;
    case 'not_administrator':
      return <p className="action-error" role="alert">当前连接不是管理会话，本控制台无法读取任务执行状态。</p>;
    case 'error':
      return <p className="action-error" role="alert">
        {outcome.status === 0 ? '无法连接本地服务，未取得任何任务状态。' : `读取任务状态失败（HTTP ${outcome.status}），未取得任何任务状态。`}
      </p>;
    case 'view': {
      const view = outcome.view;
      const guidance = taskExecutionUnresolvedGuidance(view);
      return <>
        <p role="status"><strong>{taskExecutionStateLabel(view)}</strong></p>
        <dl>
          <dt>目标</dt><dd className="resource-cell">{view.target}</dd>
          <dt>后端原因码</dt><dd className="resource-cell">{view.reason_code}</dd>
          <dt>策略版本 / 摘要</dt><dd className="resource-cell">修订 {view.policy_revision} · {view.policy_digest.slice(0, 16)}…</dd>
          <dt>命令 argv 摘要</dt><dd className="resource-cell">{view.argv_digest.slice(0, 16)}…（未保存原文）</dd>
          {view.remote_exit_code !== undefined && <><dt>{view.state === 'succeeded' ? '远端退出码' : 'CLI 返回码（远端归属未确认）'}</dt><dd>{view.remote_exit_code}</dd></>}
          {view.started_at && <><dt>开始时间</dt><dd>{new Date(view.started_at).toLocaleString()}</dd></>}
          {view.finished_at && <><dt>结束时间</dt><dd>{new Date(view.finished_at).toLocaleString()}</dd></>}
          {view.output && <>
            <dt>输出摘要</dt>
            <dd className="resource-cell">
              {view.output.digest.slice(0, 16)}… · {view.output.bytes} 字节{view.output.truncated ? '（已截断）' : ''}
            </dd>
          </>}
        </dl>
        <details>
          <summary>审批 / 预留 / 任务 / 回执关联</summary>
          <ul className="discovery-paths">
            {taskExecutionLinkage(view).map((row) => <li key={row.label}>{row.label}：<span className="resource-cell">{row.value}</span></li>)}
          </ul>
        </details>
        {view.note && <p className="page-desc">{view.note}</p>}
        {guidance && <p className="notice" role="status">{guidance}</p>}
        <p className="page-desc">{taskExecutionStopBoundary(view)}</p>
        <p className="page-desc">{taskExecutionRedactionNote(view)}</p>
      </>;
    }
  }
}
