/**
 * 通用数据加载 hook：尝试从控制面 API 拉取列表；
 * 控制面不可达时安全降级为本地示例数据并标记 disconnected，
 * 页面据此渲染"未连接"空态 —— 不阻塞构建、不阻塞路由。
 *
 * 写操作支持：
 * - `mutate(updater)`：乐观更新当前行集（如确认/驳回后移除一行），不触发网络请求；
 * - `refresh()`：重新拉取后端列表（POST 操作落库后与后端状态同步）。
 */

import { useEffect, useRef, useState } from 'react';
import { get, describeApiError } from '@/api/client';

export type ApiConnectionStatus = 'loading' | 'connected' | 'disconnected';

export interface UseApiListResult<T> {
  /** 展示用数据：connected 时为后端数据；disconnected 时为本地示例 */
  rows: T[];
  status: ApiConnectionStatus;
  /** 最近一次错误信息（用于展示，不阻断页面） */
  error: string | null;
  reload: () => void;
  /** 与 reload 同义的再拉取（语义：写操作后与后端同步） */
  refresh: () => void;
  /** 乐观更新当前行集（如操作后移除/更新一行） */
  mutate: (updater: (current: T[]) => T[]) => void;
}

export function useApiList<T>(
  path: string,
  placeholder: T[],
): UseApiListResult<T> {
  const [rows, setRows] = useState<T[]>(placeholder);
  const [status, setStatus] = useState<ApiConnectionStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const requestSeq = useRef(0);

  const reload = () => {
    const seq = ++requestSeq.current;
    setStatus('loading');
    setError(null);

    get<T[]>(path)
      .then((data) => {
        if (seq !== requestSeq.current) return; // 过期响应丢弃
        setRows(Array.isArray(data) ? data : placeholder);
        setStatus('connected');
      })
      .catch((err: unknown) => {
        if (seq !== requestSeq.current) return;
        setRows(placeholder);
        setStatus('disconnected');
        setError(describeApiError(err, '数据加载失败'));
      });
  };

  const refresh = reload;

  const mutate = (updater: (current: T[]) => T[]) => {
    setRows((prev) => (Array.isArray(prev) ? updater(prev) : prev));
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  return { rows, status, error, reload, refresh, mutate };
}
