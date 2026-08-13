/**
 * 通用数据加载 hook：尝试从控制面 API 拉取列表；
 * 后端未联调（网络失败）时安全降级为 placeholder 数据并标记 disconnected，
 * 页面据此渲染"未连接"空态 —— 不阻塞构建、不阻塞路由。
 */

import { useEffect, useRef, useState } from 'react';
import { get, ApiError } from '@/api/client';

export type ApiConnectionStatus = 'loading' | 'connected' | 'disconnected';

export interface UseApiListResult<T> {
  /** 展示用数据：connected 时为后端数据；disconnected 时为 placeholder */
  rows: T[];
  status: ApiConnectionStatus;
  /** 最近一次错误信息（用于展示，不阻断页面） */
  error: string | null;
  reload: () => void;
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
        setError(
          err instanceof ApiError
            ? `${err.message}${err.status ? `（HTTP ${err.status}）` : ''}`
            : '数据加载失败',
        );
      });
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  return { rows, status, error, reload };
}
