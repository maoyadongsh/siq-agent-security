/**
 * ENT-014-UI：单条权限事实（原生 details/summary，键盘可展开）。
 * 只展示后端返回的已有字段；后端文本一律按普通文本渲染。
 * 不展示 delegated_user / conditions 原始 JSON（见交付限制）。
 * 有效期提示是展示层判定（按当前设备时间），不改变后端 state；
 * 过期记录不使用无保留的绿色成功视觉。
 */
import type { PermissionFactRow } from '@/api/types';
import { permissionStateLabel } from '@/ui/verification';
import { domainLabel } from './PermissionFactsFilters';
import { assessValidity, permissionStateExplanation } from './permissionFacts';

interface PermissionFactItemProps {
  row: PermissionFactRow;
  /** 当前设备时间戳（毫秒），由父组件统一注入并周期性刷新 */
  now: number;
}

const SUBJECT_TYPE_LABELS: Record<string, string> = {
  agent_instance: '智能体实例',
  agent_asset: '智能体资产',
  identity_binding: '身份绑定',
};

const EFFECT_LABELS: Record<string, string> = { allow: '允许', deny: '拒绝' };

function textOrMissing(value: string | null): string {
  return value == null || value === '' ? '未提供' : value;
}

export default function PermissionFactItem({ row, now }: PermissionFactItemProps) {
  const validity = assessValidity(row, now);
  const expired = validity.kind === 'expired' || validity.kind === 'invalid';
  return (
    <details className={`pf-item${expired ? ' pf-item-expired' : ''}`}>
      <summary className="pf-item-summary" aria-label={`查看详情：${row.action} ${row.resource_value}`}>
        <span className="pf-cell pf-cell-domain">{domainLabel(row.domain)}</span>
        <span className="pf-cell pf-cell-action">{row.action}</span>
        <span className="pf-cell pf-cell-resource">
          <code title={row.resource_value}>{row.resource_value}</code>
        </span>
        <span className="pf-cell pf-cell-effect">{Object.hasOwn(EFFECT_LABELS, row.effect) ? EFFECT_LABELS[row.effect] : row.effect}</span>
        <span className="pf-cell pf-cell-state">
          <span className={`state-tag ${row.state}`} title={row.state}>
            {permissionStateLabel(row.state)}
          </span>
        </span>
        <span className="pf-cell pf-cell-authority">{row.authority}</span>
        <span className={`pf-cell pf-cell-validity pf-validity-${validity.kind}`}>{validity.message}</span>
        <span className="pf-cell pf-cell-toggle">查看详情</span>
      </summary>
      <div className="pf-detail">
        <dl className="pf-detail-grid">
          <div>
            <dt>主体类型</dt>
            <dd>{Object.hasOwn(SUBJECT_TYPE_LABELS, row.subject_type) ? SUBJECT_TYPE_LABELS[row.subject_type] : row.subject_type}（{row.subject_type}）</dd>
          </div>
          <div>
            <dt>主体 ID</dt>
            <dd className="pf-break">{row.subject_id}</dd>
          </div>
          <div>
            <dt>环境 ID</dt>
            <dd className="pf-break">{textOrMissing(row.environment_id)}</dd>
          </div>
          <div>
            <dt>权限域 / 动作</dt>
            <dd>
              {domainLabel(row.domain)}（{row.domain}） / {row.action}
            </dd>
          </div>
          <div>
            <dt>资源</dt>
            <dd className="pf-break">
              {row.resource_type} = {row.resource_value}
            </dd>
          </div>
          <div>
            <dt>效果</dt>
            <dd>
              {Object.hasOwn(EFFECT_LABELS, row.effect) ? EFFECT_LABELS[row.effect] : row.effect}（{row.effect}）
            </dd>
          </div>
          <div>
            <dt>事实状态</dt>
            <dd>
              {permissionStateLabel(row.state)}（{row.state}）— {permissionStateExplanation(row.state)}
            </dd>
          </div>
          <div>
            <dt>权威来源 / Revision</dt>
            <dd className="pf-break">
              {row.authority} / {textOrMissing(row.authority_revision)}
            </dd>
          </div>
          <div>
            <dt>生效时间（valid_from）</dt>
            <dd>{textOrMissing(row.valid_from)}</dd>
          </div>
          <div>
            <dt>失效时间（valid_until）</dt>
            <dd>{textOrMissing(row.valid_until)}</dd>
          </div>
          <div>
            <dt>有效期提示</dt>
            <dd>{validity.message}</dd>
          </div>
          <div>
            <dt>证据 ID</dt>
            <dd>
              {row.evidence_ids.length === 0 ? (
                '未提供'
              ) : (
                <ul className="pf-evidence-list">
                  {row.evidence_ids.map((id) => (
                    <li key={id} className="pf-break">
                      <code>{id}</code>
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </div>
        </dl>
        <p className="pf-detail-note">
          以上均为后端返回字段的原文展示；证据 ID 仅为标识，不代表证据内容已被核验。生效状态不等于已通过行为阻断验证。
        </p>
      </div>
    </details>
  );
}
