import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { localApi } from './api';
import type { Confirmation, Grant } from './types';

interface Inbox {
  items: Confirmation[];
  grants: Grant[];
  error: string | null;
  loading: boolean;
  refresh: (force?: boolean) => Promise<void>;
  resolve: (item: Confirmation, approve: boolean, actorId: string) => Promise<{ receipt_id: string; action: string }>;
}
const Context = createContext<Inbox | null>(null);

export function ConfirmationProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Confirmation[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(false);
  const fetching = useRef(false);
  const working = useRef(false);
  const generation = useRef(0);
  const refresh = useCallback(async (force = false) => {
    if (fetching.current && !force) return;
    fetching.current = true;
    const ticket = ++generation.current;
    try {
      const [runtime, permissions] = await Promise.all([localApi.confirmations(), localApi.grants()]);
      if (!alive.current || ticket !== generation.current) return;
      setItems(runtime.items);
      setGrants(permissions.grants ?? []);
      setError(null);
    } catch (err) {
      if (alive.current && ticket === generation.current) setError(err instanceof Error ? err.message : '无法读取待办');
    } finally {
      if (ticket === generation.current) {
        fetching.current = false;
        if (alive.current) setLoading(false);
      }
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void refresh(true);
    const poll = window.setInterval(() => { if (!working.current) void refresh(); }, 5000);
    return () => { alive.current = false; generation.current += 1; window.clearInterval(poll); };
  }, [refresh]);
  const resolve = useCallback(async (item: Confirmation, approve: boolean, actorId: string) => {
    if (working.current) throw new Error('正在处理确认，请等待状态更新');
    working.current = true;
    generation.current += 1;
    try {
      return await localApi.resolveConfirmation(item, approve, actorId);
    } finally {
      if (alive.current) await refresh(true);
      working.current = false;
    }
  }, [refresh]);
  const value = useMemo(() => ({ items, grants, error, loading, refresh, resolve }), [items, grants, error, loading, refresh, resolve]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useConfirmations(): Inbox {
  const context = useContext(Context);
  if (!context) throw new Error('ConfirmationProvider required');
  return context;
}
