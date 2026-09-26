import { useState } from 'react';
import PageHeader from '@/components/PageHeader';
import AuditSearchForm from '@/components/audit-search/AuditSearchForm';
import AuditSearchResults from '@/components/audit-search/AuditSearchResults';
import {
  EMPTY_AUDIT_FILTERS,
  auditFiltersEqual,
  auditFiltersKey,
  describeAppliedFilters,
  identityKey,
  type AuditSearchFilters,
} from '@/components/audit-search/auditSearch';
import {
  AUDIT_CORRELATION_NOTE,
  auditCorrelationFilters,
  type AuditCorrelationKind,
} from '@/components/audit-search/auditCorrelation';
import { useConsoleContext } from '@/components/ConsoleContext';
import type { ApiConnectionStatus } from '@/hooks/useApiList';
import type { AuditEvent } from '@/api/types';

/** 控制面不可达时的安全示例数据；已连接时由 GET /audit-events 覆盖 */
const PLACEHOLDER_EVENTS: AuditEvent[] = [
  {
    id: 'aud-00001',
    actor_type: 'user',
    actor_id: 'admin@siq.local',
    action: 'agent.confirm',
    resource_type: 'agent_asset',
    resource_id: 'agt-01h2kd93nf',
    decision: 'allow',
    request_id: 'req-8f2a',
    summary: {},
    created_at: '2026-08-12T09:30:00Z',
  },
  {
    id: 'aud-00002',
    actor_type: 'edge',
    actor_id: 'edge-node-01',
    action: 'evidence.batch.upload',
    resource_type: 'environment',
    resource_id: 'env-dev-docker',
    decision: 'allow',
    request_id: 'req-71bc',
    summary: { candidates: 2, evidence: 5, permission_facts: 0 },
    created_at: '2026-08-11T09:52:00Z',
  },
  {
    id: 'aud-00003',
    actor_type: 'user',
    actor_id: 'u-0001',
    action: 'finding.resolve',
    resource_type: 'finding',
    resource_id: 'fnd-0002',
    decision: 'allow',
    request_id: 'req-19de',
    summary: {},
    created_at: '2026-08-11T06:20:00Z',
  },
];

/**
 * 审计页（/audit）：只读精确查询 + 游标分页。
 * ENT-019-AUDIT-SEARCH-UI：
 * - 草稿（输入中）与已应用条件分离；只在显式提交时发起服务端查询；
 * - 结果组件按「身份 + 已应用条件」key 隔离（无歧义元组序列化），杜绝旧查询/旧身份结果混入；
 * - 权限沿用 ConsoleContext 的 access.audit（后端 audit:read 独立校验），
 *   身份未核对或无权限时不发起列表请求、不显示查询结果；
 * - CL-06-AUDIT-CORRELATION-UI：真实结果行提供「查询同请求 / 查询同对象」只读关联操作，
 *   显式替换查询条件并从第一页重新查询；相同标识仅表示标识相等，不证明完整调用链或防护效果。
 */
export default function AuditPage() {
  const context = useConsoleContext();
  const actor = context.data?.actor;
  const scope = JSON.stringify([
    context.status, context.data?.access.audit ?? false,
    context.data ? identityKey(context.data.tenant.id, actor!.id, actor!.type) : null,
  ]);
  // Reset the entire query session, including drafts and header status, not only rows.
  return <AuditPageContent key={scope} />;
}

function AuditPageContent() {
  const context = useConsoleContext();
  const [draft, setDraft] = useState<AuditSearchFilters>({ ...EMPTY_AUDIT_FILTERS });
  const [applied, setApplied] = useState<AuditSearchFilters>({ ...EMPTY_AUDIT_FILTERS });
  const [sameConditionNotice, setSameConditionNotice] = useState(false);
  const [connection, setConnection] = useState<ApiConnectionStatus>('loading');
  const [connectionError, setConnectionError] = useState<string | null>(null);

  // 门禁与 Layout 路由访问控制同源：不硬编码角色，只读 access.audit。
  const auditAllowed = context.status === 'ready' && context.data?.access.audit === true;
  // 身份键为无歧义元组序列化（不再 # 拼接）；身份未 ready 时固定占位，
  // 与任何真实身份组合键都不碰撞，且不含令牌或完整身份响应。
  const identityPart = context.data
    ? identityKey(context.data.tenant.id, context.data.actor.id, context.data.actor.type)
    : 'identity-pending';

  /** 显式提交（表单已校验）；相同条件不重复发请求，给出明确提示。 */
  const handleApply = (next: AuditSearchFilters) => {
    if (auditFiltersEqual(next, applied)) {
      setSameConditionNotice(true);
      return;
    }
    setSameConditionNotice(false);
    setApplied(next);
  };

  /** 清空：草稿与已应用条件同时重置，查询回到无过滤条件且分页重新开始。 */
  const handleClear = () => {
    setSameConditionNotice(false);
    setDraft({ ...EMPTY_AUDIT_FILTERS });
    setApplied({ ...EMPTY_AUDIT_FILTERS });
  };

  const handleDraftChange = (next: AuditSearchFilters) => {
    setSameConditionNotice(false);
    setDraft(next);
  };

  /**
   * 关联查询（CL-06）：显式操作，同步草稿与已应用条件并整体替换查询条件
   * （其余字段清空，不与上次条件 AND）；组合 key 变化使旧结果组件卸载、
   * 从第一页重新 GET。同条件重复点击走「不重复请求」提示路径。
   */
  const handleCorrelate = (event: AuditEvent, kind: AuditCorrelationKind) => {
    const next = auditCorrelationFilters(event, kind);
    if (!next) return;
    setDraft(next);
    if (auditFiltersEqual(next, applied)) {
      setSameConditionNotice(true);
      return;
    }
    setSameConditionNotice(false);
    setApplied(next);
  };

  const handleConnectionChange = (status: ApiConnectionStatus, error: string | null) => {
    setConnection((prev) => (prev === status ? prev : status));
    setConnectionError((prev) => (prev === error ? prev : error));
  };

  const appliedParts = describeAppliedFilters(applied);
  const draftDiffers = !auditFiltersEqual(draft, applied);

  return (
    <section>
      <PageHeader
        icon="audit"
        title="审计"
        description="只读查看经租户隔离和敏感信息处理的控制面审计事件，可按请求编号、对象编号等条件精确查询。"
        connection={auditAllowed ? connection : 'loading'}
        connectionError={connectionError}
      />
      {!auditAllowed ? (
        <p className="muted-text" role="status">
          {context.status === 'ready'
            ? '当前账号无审计访问权限，未发起审计查询；后端仍会独立检查每次请求。'
            : context.status === 'error'
              ? '身份与权限核对失败，未发起审计查询；这不是权限已确认，请重试核对。'
              : '正在核对审计访问权限，核对完成前不发起审计查询…'}
        </p>
      ) : (
        <>
          <div className="card audit-search-card">
            <h2>审计事件精确查询</h2>
            <AuditSearchForm
              draft={draft}
              applied={applied}
              onDraftChange={handleDraftChange}
              onApply={handleApply}
              onClear={handleClear}
            />
          </div>
          {sameConditionNotice ? (
            <p className="audit-search-note" role="status">
              查询条件与当前已应用条件相同，未发起新请求；修改条件后再次提交，或使用结果区重试入口。
            </p>
          ) : null}
          <p className="audit-search-applied" role="status">
            {appliedParts.length > 0
              ? `当前已应用查询条件：${appliedParts.join('；')}`
              : '当前未应用精确查询条件：显示本租户审计事件（服务端分页）。'}
          </p>
          {draftDiffers ? (
            <p className="audit-search-draft-hint">
              查询条件已修改但尚未提交，当前结果仍对应上方已应用条件。
            </p>
          ) : null}
          <p className="audit-search-note">{AUDIT_CORRELATION_NOTE}</p>
          <AuditSearchResults
            key={JSON.stringify([identityPart, auditFiltersKey(applied)])}
            filters={applied}
            placeholder={PLACEHOLDER_EVENTS}
            onClearFilters={handleClear}
            onConnectionChange={handleConnectionChange}
            onCorrelate={handleCorrelate}
          />
          <p className="audit-search-proof-note">
            请求编号与对象编号仅作为文本标识用于关联查询：同一请求编号不自动证明完整调用链、执行成功或防护效果。
            决策列为该事件的决策原值：allow 不代表已保护、权限已生效或执行成功。
          </p>
        </>
      )}
    </section>
  );
}
