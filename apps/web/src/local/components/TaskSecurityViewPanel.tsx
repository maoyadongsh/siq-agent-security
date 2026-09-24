import { useEffect, useState } from 'react';
import EffectEvidenceDetails from './EffectEvidenceDetails';
import { LocalApiError, localApi } from '../api';
import { platformLabel } from '../format';
import { resultPresentation } from '../resultPresentation';
import type { TaskActivityDetail } from '../taskActivities';
import { authorizationLabel, destinationStatusLabel, type TaskSecurityView } from '../taskSecurityView';

const modeLabel: Record<string, string> = { block: '强制拦截', warn: '告警', audit_only: '仅审计' };
const modelStatusLabel: Record<string, string> = { consistent: '记录一致', mixed: '混合或部分缺失', unknown: '未知' };
const contextLabel: Record<string, string> = { sandbox_bound: '全部回执记录沙箱绑定', mixed: '部分回执记录沙箱绑定', unrecorded: '未记录沙箱绑定' };
const domainLabel: Record<string, string> = { filesystem: '文件系统', network: '网络', message: '消息接收方' };

function badgeClass(status: string): string {
  if (status === 'verified' || status === 'authorized' || status === 'observed') return 'badge badge-ok';
  if (status === 'pending' || status === 'partial' || status === 'incomplete' || status === 'mixed') return 'badge badge-pending';
  if (status === 'denied' || status === 'conflicting' || status === 'failed') return 'badge badge-off';
  return 'badge';
}

export default function TaskSecurityViewPanel({ detail }: { detail: TaskActivityDetail }) {
  const [selected, setSelected] = useState<{ view: TaskSecurityView; id: string; trigger: HTMLButtonElement }>();
  const [state, setState] = useState<{ detail: TaskActivityDetail; value?: TaskSecurityView; error?: string }>();
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    localApi.taskActivitySecurityView(detail.activity, detail.view, detail.snapshot, controller.signal).then((value) => {
      if (active) setState({ detail, value });
    }).catch((error: unknown) => {
      if (!active) return;
      setState({ detail, error: error instanceof LocalApiError && error.status === 409
        ? '活动或效果证据已变化，请刷新详情后重新核验。'
        : '任务安全视图当前不可用；授权、去向和实际结果均不能视为已确认。' });
    });
    return () => { active = false; controller.abort(); };
  }, [detail]);
  const current = state?.detail === detail ? state : undefined;
  const view = current?.value;
  const business = view?.business_object;
  const run = view?.run_mode;
  const destinations = view?.data_destinations;
  const authorization = view?.authorization;
  const actual = view?.actual_result;
  const result = actual?.result;
  const evidenceIDs = result ? [...new Set([...result.requirements.flatMap((item) => item.evidence_ids), ...result.incident_ids])] : [];
  const selectedEvidence = selected && selected.view === view && evidenceIDs.includes(selected.id) ? selected : undefined;
  return <section className="task-security-view" aria-label="任务安全视图">
    <div className="task-security-heading">
      <div>
        <p className="section-kicker">可信任务状态</p>
        <h2>运行结果与权限</h2>
      </div>
      {view ? <span className="badge">证据快照 {view.snapshot.slice(0, 10)}…</span> : null}
    </div>
    <p className="page-desc">先查看结果是否已核验。工具获准执行，不代表整个任务已完成。</p>
    {!current ? <p role="status">正在生成服务端安全摘要…</p> : null}
    {current?.error ? <p role="alert" className="action-error">{current.error}</p> : null}
    {view ? <>
      <div className="task-security-grid" aria-label="任务安全摘要">
        <article className="task-security-card task-security-card-wide">
          <div className="task-security-card-title"><h3>真实结果</h3><span className={badgeClass(actual!.status)}>{resultPresentation(actual!.status, actual!.reason_code).label}</span></div>
          <p>{resultPresentation(actual!.status, actual!.reason_code).explanation}</p>
          <p className="page-desc">{resultPresentation(actual!.status, actual!.reason_code).next}</p>
          {result?.requirements.map((item, index) => {
            const presentation = resultPresentation(item.status, item.reason_code);
            return <section className="task-security-requirement" key={item.requirement_id} aria-label={`结果要求 ${index + 1}`}>
              <div className="task-security-card-title"><h4>结果要求 {index + 1}</h4><span className={badgeClass(item.status)}>{presentation.label}</span></div>
              <p>{presentation.explanation}</p>
              {item.evidence_ids.length ? <div className="toolbar">
                {item.evidence_ids.map((evidenceID, evidenceIndex) => <button className="btn" key={evidenceID}
                  onClick={(event) => setSelected({ view, id: evidenceID, trigger: event.currentTarget })}>查看证据 {evidenceIndex + 1}</button>)}
              </div> : <p>尚无对应证据，可在收到观测后刷新详情。</p>}
              <details><summary>核验标识</summary><p>要求：<code>{item.requirement_id}</code></p><p>原因码：<code>{item.reason_code}</code></p></details>
            </section>;
          })}
          {result?.incident_ids.length ? <section aria-label="相关安全事件">
            <p className="action-error">有 {result.incident_ids.length} 份安全事件证据需要核查。</p>
            <div className="toolbar">{result.incident_ids.map((evidenceID, index) => <button className="btn" key={evidenceID}
              onClick={(event) => setSelected({ view, id: evidenceID, trigger: event.currentTarget })}>查看事件证据 {index + 1}</button>)}</div>
          </section> : null}
          <p className="page-desc">正式报告和业务文件请到发起任务的业务系统查看。已采集的工具输出单独列示，不能替代正式产物；证据详情用于核对执行效果。</p>
          <p>核验时间：{new Date(view.evaluated_at).toLocaleString()}。结论只覆盖本次快照中的调用记录与结果证据。</p>
        </article>

        <article className="task-security-card">
          <div className="task-security-card-title"><h3>业务对象</h3><span className={badgeClass(business!.status)}>{business!.status === 'verified' ? '签名意图已核验' : business!.status === 'referenced' ? '仅有引用' : '对象未知'}</span></div>
          <dl className="task-security-list">
            <div><dt>对象类型</dt><dd>任务</dd></div>
            <div><dt>任务引用</dt><dd>{business!.task_id ?? '未知'}</dd></div>
            <div><dt>意图引用</dt><dd>{business!.intent_id ?? '未知'}</dd></div>
            <div><dt>业务名称</dt><dd>本机回执未提供</dd></div>
          </dl>
        </article>

        <article className="task-security-card">
          <div className="task-security-card-title"><h3>运行模式</h3><span className={badgeClass(run!.mode_status)}>{run!.mode_status === 'consistent' ? '模式一致' : run!.mode_status === 'mixed' ? '模式混合' : '模式未知'}</span></div>
          <dl className="task-security-list">
            <div><dt>智能体平台</dt><dd>{run!.platform ? platformLabel(run!.platform) : '未知'}</dd></div>
            <div><dt>执行策略</dt><dd>{run!.enforcement_modes.length ? run!.enforcement_modes.map((mode) => modeLabel[mode]).join('、') : '未记录'}</dd></div>
            <div><dt>模型路由</dt><dd>{run!.model_keys.length ? run!.model_keys.join('、') : '未记录'} · {modelStatusLabel[run!.model_status]}</dd></div>
            <div><dt>执行边界</dt><dd>{contextLabel[run!.execution_context]}</dd></div>
            <div><dt>沙箱绑定</dt><dd>{run!.sandbox_bound_receipts}/{view.activity.receipt_count} 条回执</dd></div>
          </dl>
        </article>

        <article className="task-security-card">
          <div className="task-security-card-title"><h3>数据去向</h3><span className={badgeClass(destinations!.status)}>{destinationStatusLabel[destinations!.status]}</span></div>
          {destinations!.destinations.length ? <ul className="task-security-destinations">
            {destinations!.destinations.map((item) => <li key={`${item.domain}:${item.resource_ref}`}>
              <strong>{domainLabel[item.domain]}</strong>
              <code title={`sha256:${item.resource_ref}`}>sha256:{item.resource_ref.slice(0, 12)}…</code>
              <span>{item.effects.length ? item.effects.join('、') : '效果类型未记录'} · {item.receipt_count} 条回执</span>
            </li>)}
          </ul> : <p>没有可核验的匿名去向引用。</p>}
          <p>{destinations!.unresolved_receipt_count ? `${destinations!.unresolved_receipt_count} 条涉及数据的回执缺少可核验去向。` : '涉及数据的回执均带匿名去向引用。'} 默认视图不暴露路径、主机或接收方明文。</p>
        </article>

        <article className="task-security-card">
          <div className="task-security-card-title"><h3>授权状态</h3><span className={badgeClass(authorization!.status)}>{authorizationLabel[authorization!.status]}</span></div>
          <dl className="task-security-list">
            <div><dt>允许/脱敏后允许</dt><dd>{authorization!.decisions.authorized}</dd></div>
            <div><dt>拒绝</dt><dd>{authorization!.decisions.denied}</dd></div>
            <div><dt>需批准裁决</dt><dd>{authorization!.decisions.pending}</dd></div>
            <div><dt>无法确认</dt><dd>{authorization!.decisions.unknown}</dd></div>
            <div><dt>匹配授权数</dt><dd>{authorization!.matched_grant_count}</dd></div>
          </dl>
          <p>结论按记录中的动作统计。“需批准裁决”不表示当前仍待审批，也不代表未来动作持续获准。</p>
        </article>


      </div>
      <details className="task-security-release"><summary>技术详情：部署核验范围</summary>
        <strong>候选与部署门禁：未核验</strong>
        <span>运行时没有接入原生候选门禁证据（{view.release_assurance.reason_code}）。当前任务视图不能替代 CI-01、OpenShell 资源审计或生产发布批准。</span>
      </details>
    </> : null}
    {result && selectedEvidence
      ? <EffectEvidenceDetails key={selectedEvidence.id} id={selectedEvidence.id} taskId={result.task_id} close={() => { selectedEvidence.trigger.focus(); setSelected(undefined); }} /> : null}
  </section>;
}
