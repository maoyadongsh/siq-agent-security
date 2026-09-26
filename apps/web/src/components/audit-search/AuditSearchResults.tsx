/**
 * ENT-019-AUDIT-SEARCH-UI：按已应用查询条件展示的审计结果（只读）。
 *
 * 隔离模型：父组件以「身份 + 已应用条件」作为本组件的 key；条件或身份变化时
 * 本组件整体卸载重建，组件内部再以 requestSeq 使迟到响应失效。因此：
 * - 新查询开始后绝不把上一组查询的结果展示成当前查询结果；
 * - 旧查询的迟到成功/失败、旧分页响应都不会写入新组件；
 * - 每个组件实例的 filters 在其生命周期内不变，加载更多始终携带同一组已应用条件。
 *
 * 分页/错误语义与 hooks/useApiList 当前源码保持一致（单一 error 状态、
 * 请求成功即清除、分页失败保留已加载记录并可重试），但支持过滤参数；
 * 共享 hook 未改动。
 */
import { useEffect, useRef, useState } from 'react';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { describeApiError, getListPage } from '@/api/client';
import { formatListCoverage, type ListMeta } from '@/api/listMeta';
import type { ApiConnectionStatus } from '@/hooks/useApiList';
import type { AuditEvent } from '@/api/types';
import { buildAuditQuery, hasActiveAuditFilters, type AuditSearchFilters } from './auditSearch';
import { auditCorrelationActions, type AuditCorrelationKind } from './auditCorrelation';
import './audit-search.css';

/** 仅当 VITE_DEMO_PLACEHOLDERS=true 时，断连才填充示例行（与 useApiList 同口径）。 */
const DEMO_PLACEHOLDERS: boolean = import.meta.env.VITE_DEMO_PLACEHOLDERS === 'true';

const PAGE_LIMIT = 50;

const EMPTY_META: ListMeta = { limit: null, returned: null, truncated: null, nextCursor: null, total: null };

/** 决策原值仅映射既有语义色；未知原值不给颜色，也不得推断为保护/执行成功。 */
const decisionTag: Record<string, string> = {
  allow: 'tag-ok',
  deny: 'tag-err',
};

/** 关联操作列：仅真实 connected 结果中的有效标识生成原生按钮；缺失/异常值保持文本提示。 */
function correlationCell(e: AuditEvent, onCorrelate: (event: AuditEvent, kind: AuditCorrelationKind) => void) {
  const actions = auditCorrelationActions(e);
  if (actions.length === 0) {
    return <span className="audit-search-missing">无可关联标识</span>;
  }
  return (
    <span className="audit-correlation-actions">
      {actions.map((action) => (
        <button
          key={action.kind}
          type="button"
          className="btn-sm audit-correlation-btn"
          aria-label={action.accessibleName}
          title={action.accessibleName}
          onClick={() => onCorrelate(e, action.kind)}
        >
          {action.kind === 'request' ? '查询同请求' : '查询同对象'}
        </button>
      ))}
    </span>
  );
}

const baseColumns: TableColumn<AuditEvent>[] = [
  {
    key: 'id',
    header: '事件 ID',
    render: (e) => <span className="mono audit-search-break">{e.id}</span>,
  },
  { key: 'created_at', header: '发生时间', render: (e) => e.created_at },
  {
    key: 'action',
    header: '动作',
    render: (e) => <span className="mono audit-search-break">{e.action}</span>,
  },
  {
    key: 'actor',
    header: '操作者（类型:编号）',
    render: (e) => (
      <span className="audit-search-break" title={`${e.actor_type}:${e.actor_id}`}>
        {e.actor_type}:<span className="mono">{e.actor_id}</span>
      </span>
    ),
  },
  {
    key: 'resource',
    header: '对象（类型:编号）',
    render: (e) => (
      <span className="audit-search-break">
        {e.resource_type}:
        {e.resource_id !== null ? (
          <span className="mono">{e.resource_id}</span>
        ) : (
          <span className="audit-search-missing">未提供</span>
        )}
      </span>
    ),
  },
  {
    key: 'decision',
    header: '决策原值',
    render: (e) => <span className={`tag ${decisionTag[e.decision] ?? ''}`}>{e.decision}</span>,
  },
  {
    key: 'request_id',
    header: '请求编号',
    render: (e) =>
      e.request_id !== null ? (
        <span className="mono audit-search-break">{e.request_id}</span>
      ) : (
        <span className="audit-search-missing">未提供</span>
      ),
  },
];

interface AuditSearchResultsProps {
  /** 已应用条件；本组件按 key 隔离，生命周期内不变 */
  filters: AuditSearchFilters;
  /** 断连且 VITE_DEMO_PLACEHOLDERS=true 时的显式演示占位 */
  placeholder: AuditEvent[];
  /** 无匹配的过滤查询时提供清空入口 */
  onClearFilters: () => void;
  /** 向页头回报连接状态（不改变本组件状态所有权） */
  onConnectionChange?: (status: ApiConnectionStatus, error: string | null) => void;
  /**
   * 关联查询（CL-06）：仅真实 connected 结果中调用；父组件据此同步草稿与已应用条件
   * 并从第一页重新查询。演示占位/断连/加载态不渲染关联按钮，故不会触发。
   */
  onCorrelate?: (event: AuditEvent, kind: AuditCorrelationKind) => void;
}

export default function AuditSearchResults({
  filters,
  placeholder,
  onClearFilters,
  onConnectionChange,
  onCorrelate,
}: AuditSearchResultsProps) {
  const [rows, setRows] = useState<AuditEvent[]>([]);
  const [status, setStatus] = useState<ApiConnectionStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [listMeta, setListMeta] = useState<ListMeta | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const requestSeq = useRef(0);
  const connectionChangeRef = useRef(onConnectionChange);
  useEffect(() => {
    connectionChangeRef.current = onConnectionChange;
  });
  useEffect(() => {
    connectionChangeRef.current?.(status, error);
  }, [status, error]);

  const filtered = hasActiveAuditFilters(filters);

  const fetchPage = (cursor: string | undefined, append: boolean) => {
    const seq = ++requestSeq.current;
    if (append) {
      setLoadingMore(true);
    } else {
      setStatus('loading');
      setError(null);
    }

    // 过滤条件与 cursor/limit/include_total 合并为同一 query 对象，
    // 由客户端 buildUrl（URL.searchParams）统一编码；不手工拼接查询字符串。
    getListPage<AuditEvent>('/audit-events', {
      query: {
        ...buildAuditQuery(filters),
        limit: PAGE_LIMIT,
        cursor,
        include_total: true,
      },
    })
      .then(({ items, meta }) => {
        if (seq !== requestSeq.current) return;
        setRows((prev) => (append ? [...prev, ...items] : items));
        setListMeta(meta);
        setStatus('connected');
        setError(null);
        setLoadingMore(false);
      })
      .catch((err: unknown) => {
        if (seq !== requestSeq.current) return;
        if (!append) {
          setRows(DEMO_PLACEHOLDERS ? placeholder : []);
          setListMeta(null);
          setStatus('disconnected');
          setError(
            err instanceof Error && err.message.includes('协议')
              ? err.message
              : describeApiError(err, '数据加载失败'),
          );
        } else {
          setError(describeApiError(err, '加载更多失败'));
        }
        setLoadingMore(false);
      });
  };

  // 首屏加载：filters 由 key 固定，只在挂载时请求一次；卸载时令在途响应失效。
  useEffect(() => {
    fetchPage(undefined, false);
    return () => {
      requestSeq.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reload = () => {
    fetchPage(undefined, false);
  };

  const loadMore = () => {
    if (loadingMore) return;
    if (!listMeta?.truncated || !listMeta.nextCursor) return;
    fetchPage(listMeta.nextCursor, true);
  };

  const hasMore = listMeta?.truncated === true && Boolean(listMeta.nextCursor);
  const coverageText =
    status === 'connected' ? formatListCoverage(listMeta ?? EMPTY_META, rows.length) : null;

  // 关联操作列只在真实 connected 结果中追加：演示占位、断连、加载态不渲染关联按钮。
  const columns =
    status === 'connected' && onCorrelate
      ? [
          ...baseColumns,
          {
            key: 'correlation',
            header: '关联查询',
            render: (e: AuditEvent) => correlationCell(e, onCorrelate),
          },
        ]
      : baseColumns;

  return (
    <div className="audit-search-results">
      {status === 'loading' ? (
        <p className="muted-text" role="status">
          正在按当前已应用条件加载审计事件…
        </p>
      ) : null}

      {status === 'disconnected' ? (
        <>
          <DisconnectedNotice error={error} onRetry={reload} />
          {rows.length > 0 ? (
            <>
              <p className="audit-search-note" role="status">
                以下为显式演示占位数据（非真实审计记录），不提供查询语义。
              </p>
              <SimpleTable columns={columns} rows={rows} rowKey={(e) => e.id} />
            </>
          ) : null}
        </>
      ) : null}

      {status === 'connected' ? (
        <>
          {coverageText ? (
            <p className="list-coverage" role="status">
              {coverageText}
            </p>
          ) : null}
          {rows.length === 0 ? (
            filtered ? (
              <p className="muted-text" role="status">
                当前查询条件下无匹配的审计事件
                {listMeta?.total === 0 ? '（服务端匹配总数 0）' : ''}；空结果不是查询失败。
                <button type="button" className="btn-sm" onClick={onClearFilters}>
                  清空查询条件
                </button>
              </p>
            ) : (
              <p className="muted-text" role="status">
                后端成功返回空列表：当前没有审计事件记录；这不是查询失败。
              </p>
            )
          ) : (
            <SimpleTable columns={columns} rows={rows} rowKey={(e) => e.id} />
          )}
          {error ? (
            <p className="action-error" role="alert">
              {error}（已保留此前成功加载的记录，不代表全部加载成功）
            </p>
          ) : null}
          {hasMore ? (
            <div className="list-more">
              <button
                type="button"
                className="btn-sm"
                disabled={loadingMore}
                onClick={loadMore}
              >
                {loadingMore ? '加载中…' : '加载更多'}
              </button>
              <span className="audit-search-more-note">存在尚未加载的匹配记录；加载更多保留当前全部查询条件。</span>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
