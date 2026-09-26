/**
 * ENT-018-FINDINGS-UI：单条风险（原生 details/summary，键盘可展开）。
 * 只展示后端 Finding 已有字段；缺失显示「未提供」；证据/资产 ID 仅作标识文本。
 * 后端文本一律普通文本渲染；不展开 risk_acceptance 原始 JSON。
 * 处置按钮经 renderActions 由页面注入，业务逻辑不在本组件。
 */
import type { ReactNode } from 'react';
import type { Finding } from '@/api/types';
import { isFinalStatus, severityLabel, statusLabel } from './findingExplorer';

/** 级别/状态标签类（沿用全局 .tag 色系；颜色之外均有文本）。 */
export const SEVERITY_TAG_CLASS: Record<string, string> = {
  critical: 'tag-err',
  high: 'tag-err',
  medium: 'tag-warn',
  low: 'tag-info',
  info: '',
};

export const STATUS_TAG_CLASS: Record<string, string> = {
  open: 'tag-err',
  acknowledged: 'tag-warn',
  resolved: 'tag-ok',
  risk_accepted: 'tag-info',
};

interface FindingExplorerItemProps {
  finding: Finding;
  /** 页面注入的处置操作（确认/解决）；终态记录页面传 null */
  renderActions?: (finding: Finding) => ReactNode;
}

function textOrMissing(value: string | null): string {
  return value == null || value === '' ? '未提供' : value;
}

export default function FindingExplorerItem({ finding, renderActions }: FindingExplorerItemProps) {
  const severityClass = Object.hasOwn(SEVERITY_TAG_CLASS, finding.severity) ? SEVERITY_TAG_CLASS[finding.severity] : '';
  const statusClass = Object.hasOwn(STATUS_TAG_CLASS, finding.status) ? STATUS_TAG_CLASS[finding.status] : '';
  return (
    <div className="finding-explorer-item">
      <details className="finding-explorer-disclosure">
        <summary
          className="finding-explorer-summary"
          aria-label={`查看详情：${finding.rule_id} ${finding.impact ?? finding.id}`}
        >
        <span className="finding-explorer-cell finding-explorer-cell-severity">
          <span className={`tag ${severityClass}`}>
            {severityLabel(finding.severity)}（{finding.severity}）
          </span>
        </span>
        <span className="finding-explorer-cell finding-explorer-cell-rule mono" title={`v${finding.rule_version}`}>
          {finding.rule_id}
        </span>
        <span className="finding-explorer-cell finding-explorer-cell-asset">
          {finding.asset_id ?? '未提供'}
        </span>
        <span className="finding-explorer-cell finding-explorer-cell-impact">
          {finding.impact ?? '未提供'}
        </span>
        <span className="finding-explorer-cell finding-explorer-cell-status">
          <span className={`tag ${statusClass}`} title={finding.status}>
            {finding.status}
            {finding.owner_user_id ? ` · ${finding.owner_user_id}` : ''}
          </span>
        </span>
        <span className="finding-explorer-cell finding-explorer-cell-toggle">查看详情</span>
      </summary>
      <div className="finding-explorer-detail">
        <dl className="finding-explorer-detail-grid">
          <div>
            <dt>风险 ID</dt>
            <dd className="finding-explorer-break">{finding.id}</dd>
          </div>
          <div>
            <dt>规则 ID / 版本</dt>
            <dd className="finding-explorer-break">
              {finding.rule_id} / v{finding.rule_version}
            </dd>
          </div>
          <div>
            <dt>级别</dt>
            <dd>
              {severityLabel(finding.severity)}（{finding.severity}）
            </dd>
          </div>
          <div>
            <dt>风险域</dt>
            <dd>{textOrMissing(finding.domain)}</dd>
          </div>
          <div>
            <dt>关联资产 ID</dt>
            <dd className="finding-explorer-break">{textOrMissing(finding.asset_id)}</dd>
          </div>
          <div>
            <dt>风险描述</dt>
            <dd className="finding-explorer-break">{textOrMissing(finding.impact)}</dd>
          </div>
          <div>
            <dt>修复建议</dt>
            <dd className="finding-explorer-break">{textOrMissing(finding.remediation)}</dd>
          </div>
          <div>
            <dt>当前处置状态</dt>
            <dd>
              {finding.status}（{statusLabel(finding.status)}）
              {isFinalStatus(finding.status) ? '；已终态' : ''}
            </dd>
          </div>
          <div>
            <dt>负责人标识</dt>
            <dd className="finding-explorer-break">{textOrMissing(finding.owner_user_id)}</dd>
          </div>
          <div>
            <dt>首次观察时间</dt>
            <dd>{finding.first_seen_at}</dd>
          </div>
          <div>
            <dt>最近观察时间</dt>
            <dd>{finding.last_seen_at}</dd>
          </div>
          <div>
            <dt>到期时间</dt>
            <dd>{textOrMissing(finding.due_at)}</dd>
          </div>
          <div>
            <dt>证据 ID</dt>
            <dd>
              {finding.evidence_ids.length === 0 ? (
                '未提供'
              ) : (
                <ul className="finding-explorer-evidence-list">
                  {finding.evidence_ids.map((id) => (
                    <li key={id} className="finding-explorer-break">
                      <code>{id}</code>
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </div>
        </dl>
        <p className="finding-explorer-detail-note">
          以上均为后端返回字段的原文展示；证据与资产 ID 仅为标识，不代表其内容已被核验。
          确认不等于解决；解决不等于独立验证阻断生效；接受风险不等于风险已消除。
        </p>
      </div>
      </details>
      {renderActions ? (
        <div className="finding-explorer-actions">{renderActions(finding)}</div>
      ) : null}
    </div>
  );
}
