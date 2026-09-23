import { useEffect, useState } from 'react';
import { localApi } from '../api';
import Modal from '@/components/Modal';
import { effectTypeLabel } from '../resultPresentation';
import type { EffectEvidenceSummary } from '../effectEvidence';
const independence: Record<string, string> = { self_reported: '执行方自报', host_independent: '宿主独立观测', external_independent: '外部独立观测', unknown: '未知' };
const coverage: Record<string, string> = { full: '完整覆盖', partial: '部分覆盖', unknown: '覆盖未知' };
const execution: Record<string, string> = { requested: '已请求', started: '已开始', completed: '观测到完成', failed: '观测到失败', unknown: '未知' };
const result: Record<string, string> = { expected: '符合预期', unexpected: '不符合预期', conflicting: '存在冲突', unknown: '未知' };
export default function EffectEvidenceDetails({ id, taskId, close }: { id: string; taskId: string; close: () => void }) {
  const [state, setState] = useState<{ key: string; data?: EffectEvidenceSummary; error?: string }>();
  const [retry, setRetry] = useState(0);
  const key = JSON.stringify([id, taskId, retry]);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    localApi.effectEvidence(id, taskId, controller.signal).then((data) => {
      if (active) setState({ key, data });
    }).catch(() => { if (active) setState({ key, error: '这份证据当前不可读取或无法通过校验，请重试；当前无法确认其观测结果。' }); });
    return () => { active = false; controller.abort(); };
  }, [id, taskId, key]);
  const current = state?.key === key ? state : undefined;
  const data = current?.data;
  return <Modal open title="效果证据详情" onClose={close}>
    <div className="toolbar">
      <button className="btn" onClick={close}>关闭证据详情</button>
      <button className="btn" disabled={!current} onClick={() => setRetry((value) => value + 1)}>{current?.error ? '重试读取证据' : '刷新证据'}</button>
    </div>
    {!current ? <p role="status">正在读取证据…</p> : null}
    {current?.error ? <p role="alert" className="action-error">{current.error}</p> : null}
    {data ? <>
      <h3>{effectTypeLabel(data.effectType)} · {execution[data.executionState]}</h3>
      <dl className="task-security-list">
        <div><dt>观测结果</dt><dd>{result[data.result]}</dd></div>
        <div><dt>证据来源</dt><dd>{independence[data.independence]}</dd></div>
        <div><dt>覆盖范围</dt><dd>{coverage[data.coverage]}</dd></div>
        <div><dt>观测时间</dt><dd>{new Date(data.observedAt).toLocaleString('zh-CN', { hour12: false })}</dd></div>
      </dl>
      {data.finding ? <p className="action-error">{data.finding === 'unauthorized_effect_observed' ? '观测到未获授权的执行效果。' : '观测到授权范围之外的执行效果。'}</p> : null}
      <details className="block-gap"><summary>技术详情：来源与标识</summary>
        <div className="activity-identifiers">
          <p>证据：{id}</p><p>任务：{taskId}</p>
          <p>来源：{data.sourceId}（{data.sourceType}）</p>
          <p>效果类型：{data.effectType}</p>
          <p>动作引用：{data.actionId}；裁决回执：{data.receiptId}</p>
          <p>资源摘要：{data.resourceRef}</p><p>证据摘要：{data.digest}</p>
        </div>
      </details>
      <p>证据由本地服务验签。单份证据的完成状态不能替代任务效果核验结论。</p>
    </> : null}
  </Modal>;
}
