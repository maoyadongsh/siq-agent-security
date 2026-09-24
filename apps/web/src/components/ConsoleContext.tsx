import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { getConsoleContext, type ConsoleContext } from '@/api/consoleContext';

interface ContextState { data?: ConsoleContext; status: 'loading' | 'ready' | 'error'; reload: () => void }
const Context = createContext<ContextState | null>(null);
export function ConsoleContextProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<ConsoleContext>();
  const [status, setStatus] = useState<ContextState['status']>('loading');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    getConsoleContext().then(value => { if (active) { setData(value); setStatus('ready'); } })
      .catch(() => { if (active) { setData(undefined); setStatus('error'); } });
    return () => { active = false; };
  }, [retry]);
  const reload = () => { setData(undefined); setStatus('loading'); setRetry(n => n + 1); };
  return <Context.Provider value={{ data, status, reload }}>{children}</Context.Provider>;
}
export function useConsoleContext() {
  const context = useContext(Context);
  if (!context) throw new Error('Console context provider missing');
  return context;
}
