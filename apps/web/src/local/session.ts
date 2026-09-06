import { createContext, useContext } from 'react';
import type { Status } from './types';

const ACTOR_KEY = 'siq.as.local.actor-id';

export function readActorId(): string {
  try {
    return window.sessionStorage.getItem(ACTOR_KEY) || 'local';
  } catch {
    return 'local';
  }
}

export function writeActorId(id: string): void {
  try {
    window.sessionStorage.setItem(ACTOR_KEY, id);
  } catch {
    /* 隐私模式仅本次会话内存生效 */
  }
}

export interface LocalSession {
  status: Status | null;
  error: string | null;
  actorId: string;
  setActorId: (id: string) => void;
  reload: () => void;
}

export const LocalSessionContext = createContext<LocalSession | null>(null);

export function useLocalSession(): LocalSession {
  const ctx = useContext(LocalSessionContext);
  if (!ctx) {
    throw new Error('useLocalSession must be used inside local App');
  }
  return ctx;
}
