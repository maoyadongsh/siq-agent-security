import { useEffect, useRef, useState } from 'react';
import Modal from './Modal';
import { ApiError } from '@/api/client';
import { modeLabel } from '@/api/changeReview';
import { deploymentPreviewError, readDeploymentPreview, type DeploymentPreview, type DeploymentSelection } from '@/api/deploymentPreview';
import { createDeploymentSubmission } from '@/api/deploymentSubmission';

export default function DeploymentPreviewDialog({ selection, onClose, onStarting, onRejected, onViewResults, onSubmitted, onUncertain }: {
  selection: DeploymentSelection; onClose: () => void; onStarting: () => void; onRejected: () => void; onViewResults: () => void; onSubmitted: (deploymentId?: string) => void; onUncertain: () => void;
}) {
  const [value, setValue] = useState<DeploymentPreview | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const pending = useRef(false);
  const writing = useRef(false);
  const alive = useRef(true);
  async function load() {
    if (pending.current) return;
    pending.current = true; setBusy(true); setValue(null); setError(''); setConfirmed(false);
    try { const result = await readDeploymentPreview(selection); if (alive.current) setValue(result); }
    catch (e) { if (alive.current) setError(deploymentPreviewError(e)); }
    finally { pending.current = false; if (alive.current) setBusy(false); }
  }
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; }; }, []);
  async function submit() {
    if (pending.current || !value || !confirmed) return;
    pending.current = true; writing.current = true; setSubmitting(true); setError('');
    try {
      const key = crypto.randomUUID();
      onStarting();
      const result = await createDeploymentSubmission(selection, value, key);
      if (alive.current) onSubmitted(result.deployment_id);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && [400, 401, 403, 404, 409, 422, 429].includes(e.status)) {
        onRejected();
        setValue(null); setConfirmed(false); setError(deploymentPreviewError(e));
      } else onUncertain();
    } finally { pending.current = false; writing.current = false; if (alive.current) setSubmitting(false); }
  }
  const close = () => { if (!writing.current) onClose(); };
  return <Modal open onClose={close} title="确认部署目标" description="先核对策略和目标。预览不会下发策略；确认时会重新检查，内容变化需重新预览。" className="change-review-dialog">
    <div className="modal-body">
      {busy ? <p role="status">正在检查策略、目标和执行端…</p> : null}
      {error ? <><p role="alert" className="action-error">{error}</p><button type="button" className="btn" onClick={onViewResults}>查看已有部署记录</button></> : null}
      {value ? <>
        <h3>{value.policy_name} · 第 {value.policy_version} 版</h3>
        <dl className="change-review-facts"><dt>执行环境</dt><dd>{value.environment_name}</dd><dt>登记目标</dt><dd>{value.target}</dd><dt>保护方式</dt><dd>{modeLabel(value.enforcement_mode)}</dd><dt>执行后端</dt><dd>{value.backend === 'fake' ? '开发测试后端' : 'OpenShell'}</dd><dt>本次操作</dt><dd>{value.action === 'development_task' ? '创建测试下发任务，不执行实际策略' : '动态更新运行时策略'}</dd>{value.base_revision ? <><dt>当前版本</dt><dd>{value.base_revision}</dd></> : null}</dl>
        <p>{value.backend === 'fake' ? '这是开发模式任务通道，不会证明 OpenShell 已生效或工具调用被拦截。' : '提交后还需核对执行结果。配置读回通过不等于实际行为已验证。'}</p>
        <label><input type="checkbox" checked={confirmed} disabled={submitting} onChange={e => setConfirmed(e.target.checked)} />我已核对策略、环境和登记目标，确认执行上述操作。</label>
        <details><summary>技术标识</summary><p>变更：{value.change_id}</p><p>策略：{value.policy_id}</p><p>绑定：{value.binding_id}</p><p>预览摘要：{value.preview_digest}</p></details>
      </> : null}
    </div>
    <div className="modal-actions"><button type="button" className="btn" disabled={submitting} onClick={close}>取消</button><button type="button" className="btn" disabled={busy || submitting} onClick={() => void load()}>{value ? '重新预览' : '重试预览'}</button>{value ? <button type="button" className="btn btn-primary" disabled={!confirmed || submitting || busy} onClick={() => void submit()}>{submitting ? '正在提交…' : '确认并部署'}</button> : null}</div>
  </Modal>;
}
