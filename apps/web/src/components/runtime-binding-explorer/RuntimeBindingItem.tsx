/**
 * ENT-018-BINDINGS-UI：单条运行时绑定（原生 details/summary，键盘可展开）。
 * 只展示后端 RuntimeBindingRow 已有字段；缺失显示「未提供」；ID 仅作标识文本。
 * attestation 是开放字典：本组件不展开、不序列化、不复制原始 attestation，
 * 不渲染 tenant_id，不根据 attestation 推导「已验证/已保护」。
 * 后端字符串一律普通文本渲染；处置按钮经 renderActions 由页面注入。
 */
import type { ReactNode } from 'react';
import type { RuntimeBindingRow } from '@/api/types';
import { statusTagClass, textOrMissing } from './runtimeBindingExplorer';

interface RuntimeBindingItemProps {
  binding: RuntimeBindingRow;
  /** 页面注入的处置操作（吊销）；非 active 记录页面传 null */
  renderActions?: (binding: RuntimeBindingRow) => ReactNode;
}

export default function RuntimeBindingItem({ binding, renderActions }: RuntimeBindingItemProps) {
  const statusClass = statusTagClass(binding.status);
  const summaryLabel = `查看详情：绑定 ${binding.id}，后端 ${binding.backend}，目标 ${binding.backend_target_id}`;
  return (
    <div className="rb-explorer-item">
      <details className="rb-explorer-disclosure">
        <summary className="rb-explorer-summary" aria-label={summaryLabel}>
          <span className="rb-explorer-cell rb-explorer-cell-id mono" title={binding.id}>
            {binding.id}
          </span>
          <span className="rb-explorer-cell rb-explorer-cell-asset mono" title={binding.asset_id}>
            {binding.asset_id}
          </span>
          <span className="rb-explorer-cell rb-explorer-cell-instance mono" title={binding.agent_instance_id}>
            {binding.agent_instance_id}
          </span>
          <span className="rb-explorer-cell rb-explorer-cell-env mono" title={binding.environment_id}>
            {binding.environment_id}
          </span>
          <span className="rb-explorer-cell rb-explorer-cell-backend" title={binding.backend}>
            {binding.backend}
          </span>
          <span className="rb-explorer-cell rb-explorer-cell-target mono" title={binding.backend_target_id}>
            {binding.backend_target_id}
          </span>
          <span className="rb-explorer-cell rb-explorer-cell-status">
            <span className={`tag ${statusClass}`} title={binding.status}>
              {binding.status}
            </span>
          </span>
          <span className="rb-explorer-cell rb-explorer-cell-toggle">查看详情</span>
        </summary>
        <div className="rb-explorer-detail">
          <dl className="rb-explorer-detail-grid">
            <div>
              <dt>绑定 ID</dt>
              <dd className="rb-explorer-break">{binding.id}</dd>
            </div>
            <div>
              <dt>环境 ID</dt>
              <dd className="rb-explorer-break">{textOrMissing(binding.environment_id)}</dd>
            </div>
            <div>
              <dt>资产 ID</dt>
              <dd className="rb-explorer-break">{textOrMissing(binding.asset_id)}</dd>
            </div>
            <div>
              <dt>实例 ID</dt>
              <dd className="rb-explorer-break">{textOrMissing(binding.agent_instance_id)}</dd>
            </div>
            <div>
              <dt>后端</dt>
              <dd className="rb-explorer-break">{textOrMissing(binding.backend)}</dd>
            </div>
            <div>
              <dt>运行时目标 ID</dt>
              <dd className="rb-explorer-break">{textOrMissing(binding.backend_target_id)}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>
                {binding.status}
                {binding.status === 'active' ? '（绑定状态，不等于运行时防护生效）' : ''}
                {binding.status === 'revoked' ? '（绑定已撤销，不等于进程已停止或全部权限已撤销）' : ''}
              </dd>
            </div>
            <div>
              <dt>登记时间</dt>
              <dd>{textOrMissing(binding.created_at)}</dd>
            </div>
            <div>
              <dt>吊销时间</dt>
              <dd>{textOrMissing(binding.revoked_at)}</dd>
            </div>
          </dl>
          <p className="rb-explorer-detail-note">
            以上均为后端返回字段的原文展示；ID 仅为标识，不代表对应内容已被核验。
            active 表示绑定状态，不等于运行时防护生效；revoked 表示绑定已撤销，不等于进程已停止或全部权限已撤销。
            后端附加证明字段为开放字典，本页不展开、不据此推导任何防护结论。
          </p>
        </div>
      </details>
      {renderActions ? (() => {
        const actions = renderActions(binding);
        return actions ? <div className="rb-explorer-actions">{actions}</div> : null;
      })() : null}
    </div>
  );
}
