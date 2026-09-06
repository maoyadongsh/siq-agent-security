/**
 * 通用数据加载 hook：尝试从控制面 API 拉取列表。
 * DEV13-A：协议错误 / 非数组不得回退示例数据并显示「已连接」；
 * 断连时仅在显式占位允许时展示示例，并标记 disconnected。
 * DEV13-D：读取列表截断头；本页条数不得冒充全量；支持游标加载更多。
 */

import { useEffect, useRef, useState } from 'react';
import { getListPage, describeApiError } from '@/api/client';
import { formatListCoverage, type ListMeta } from '@/api/listMeta';

export type ApiConnectionStatus = 'loading' | 'connected' | 'disconnected';

export interface UseApiListResult<T> {
  /** 展示用数据：connected 时为后端数据；disconnected 时可为空或显式演示占位 */
  rows: T[];
  status: ApiConnectionStatus;
  /** 最近一次错误信息（用于展示，不阻断页面） */
  error: string | null;
  listMeta: ListMeta | null;
  /** 覆盖说明：明确本页 vs 全量 */
  coverageText: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
  reload: () => void;
  /** 与 reload 同义的再拉取（语义：写操作后与后端同步） */
  refresh: () => void;
  /** 乐观更新当前行集（如操作后移除/更新一行） */
  mutate: (updater: (current: T[]) => T[]) => void;
}

/** 仅当 VITE_DEMO_PLACEHOLDERS=true 时，断连才填充示例行（仍标记 disconnected）。 */
const DEMO_PLACEHOLDERS: boolean = import.meta.env.VITE_DEMO_PLACEHOLDERS === 'true';

const DEFAULT_PAGE_LIMIT = 50;

export function useApiList<T>(
  path: string,
  placeholder: T[],
  options?: { pageLimit?: number; includeTotal?: boolean },
): UseApiListResult<T> {
  const pageLimit = options?.pageLimit ?? DEFAULT_PAGE_LIMIT;
  const includeTotal = options?.includeTotal ?? false;
  const [rows, setRows] = useState<T[]>([]);
  const [status, setStatus] = useState<ApiConnectionStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [listMeta, setListMeta] = useState<ListMeta | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const requestSeq = useRef(0);

  const fetchPage = (cursor: string | undefined, append: boolean) => {
    const seq = ++requestSeq.current;
    if (append) {
      setLoadingMore(true);
    } else {
      setStatus('loading');
      setError(null);
    }

    getListPage<T>(path, {
      query: {
        limit: pageLimit,
        cursor,
        include_total: includeTotal ? true : undefined,
      },
    })
      .then(({ items, meta }) => {
        if (seq !== requestSeq.current) return;
        setRows((prev) => (append ? [...prev, ...items] : items));
        setListMeta(meta);
        setStatus('connected');
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

  const reload = () => {
    fetchPage(undefined, false);
  };

  const refresh = reload;

  const loadMore = () => {
    if (!listMeta?.truncated || !listMeta.nextCursor || loadingMore) return;
    fetchPage(listMeta.nextCursor, true);
  };

  const mutate = (updater: (current: T[]) => T[]) => {
    setRows((prev) => (Array.isArray(prev) ? updater(prev) : prev));
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, pageLimit, includeTotal]);

  const coverageText =
    status === 'connected' ? formatListCoverage(listMeta ?? { limit: null, returned: null, truncated: null, nextCursor: null, total: null }, rows.length) : null;

  return {
    rows,
    status,
    error,
    listMeta,
    coverageText,
    hasMore: listMeta?.truncated === true && Boolean(listMeta.nextCursor),
    loadingMore,
    loadMore,
    reload,
    refresh,
    mutate,
  };
}
