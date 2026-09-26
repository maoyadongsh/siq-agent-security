/**
 * ENT-018-POLICIES-UI：单条期望策略（原生 details/summary，键盘可展开）。
 * 只展示 PolicyRow 列表投影字段；ID 仅作标识文本；后端文本一律普通文本渲染。
 * block 显示为「期望：阻断」中性标签，绝不借用 effective/已生效语义。
 */
import type { PolicyRow } from '@/api/types';
import { extractAgentIds, modeExpectationText } from './policyExplorer';

interface PolicyExplorerItemProps {
  policy: PolicyRow;
}

function AgentIds({ policy }: { policy: PolicyRow }) {
  const view = extractAgentIds(policy.selector);
  if (view.kind === 'missing') return <span>未提供</span>;
  if (view.kind === 'invalid') return <span>格式异常（agent_ids 不是字符串数组）</span>;
  if (view.ids.length === 0) {
    return <span>空列表（不代表全部资产）</span>;
  }
  return (
    <ul className="policy-explorer-id-list">
      {view.ids.map((id, index) => (
        <li key={`${index}:${id}`} className="policy-explorer-break">
          <code>{id}</code>
        </li>
      ))}
    </ul>
  );
}

function AgentIdsSummary({ policy }: { policy: PolicyRow }) {
  const view = extractAgentIds(policy.selector);
  if (view.kind === 'missing') return <span>未提供</span>;
  if (view.kind === 'invalid') return <span>格式异常</span>;
  if (view.ids.length === 0) return <span>空列表</span>;
  return <span>{view.ids.length} 个资产</span>;
}

export default function PolicyExplorerItem({ policy }: PolicyExplorerItemProps) {
  const unsupported = policy.unsupported_by_backend;
  return (
    <details className="policy-explorer-item">
      <summary
        className="policy-explorer-summary"
        aria-label={`查看详情：${policy.name}`}
      >
        <span className="policy-explorer-cell policy-explorer-cell-name">{policy.name}</span>
        <span className="policy-explorer-cell policy-explorer-cell-version">v{policy.version}</span>
        <span className="policy-explorer-cell policy-explorer-cell-mode">
          {/* 中性标签：期望档位，不使用 effective/已生效样式 */}
          <span className="state-tag">{modeExpectationText(policy.enforcement_mode)}</span>
        </span>
        <span className="policy-explorer-cell policy-explorer-cell-status">{policy.status}</span>
        <span className="policy-explorer-cell policy-explorer-cell-unsupported">
          {unsupported.length > 0 ? `${unsupported.length} 项未覆盖` : '未覆盖项：空'}
        </span>
        <span className="policy-explorer-cell policy-explorer-cell-targets">
          <AgentIdsSummary policy={policy} />
        </span>
        <span className="policy-explorer-cell policy-explorer-cell-toggle">查看详情</span>
      </summary>
      <div className="policy-explorer-detail">
        <dl className="policy-explorer-detail-grid">
          <div>
            <dt>策略 ID</dt>
            <dd className="policy-explorer-break">{policy.id}</dd>
          </div>
          <div>
            <dt>名称</dt>
            <dd className="policy-explorer-break">{policy.name}</dd>
          </div>
          <div>
            <dt>版本</dt>
            <dd>v{policy.version}</dd>
          </div>
          <div>
            <dt>期望执行档位</dt>
            <dd>
              {modeExpectationText(policy.enforcement_mode)}（{policy.enforcement_mode}）
            </dd>
          </div>
          <div>
            <dt>策略状态（后端返回）</dt>
            <dd>{policy.status}</dd>
          </div>
          <div>
            <dt>目标资产 ID</dt>
            <dd>
              <AgentIds policy={policy} />
            </dd>
          </div>
          <div>
            <dt>后端报告的未覆盖项</dt>
            <dd>
              {unsupported.length === 0 ? (
                '空列表：本条响应未列出未覆盖项，不等于全部支持或已验证兼容'
              ) : (
                <ul className="policy-explorer-id-list">
                  {unsupported.map((item, index) => (
                    <li key={`${index}:${item}`} className="policy-explorer-break">
                      <code>{item}</code>
                    </li>
                  ))}
                </ul>
              )}
            </dd>
          </div>
          <div>
            <dt>更新时间</dt>
            <dd>{policy.updated_at}</dd>
          </div>
        </dl>
        <p className="policy-explorer-detail-note">
          这里展示期望策略；实际生效情况需结合审批、部署及独立后端读回核对。
          不因状态、档位、版本或未覆盖项为空而推断已部署、已生效或已保护。
        </p>
      </div>
    </details>
  );
}
