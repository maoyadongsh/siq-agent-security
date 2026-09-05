import { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './Layout';
import { boot, localApi } from './api';
import { LocalSessionContext, readActorId, writeActorId, type LocalSession } from './session';
import type { Status } from './types';
import OverviewPage from './pages/OverviewPage';
import AgentsPage from './pages/AgentsPage';
import AgentDetailPage from './pages/AgentDetailPage';
import PermissionsPage from './pages/PermissionsPage';
import FindingsPage from './pages/FindingsPage';
import GrantsPage from './pages/GrantsPage';
import ReceiptsPage from './pages/ReceiptsPage';
import BindingsPage from './pages/BindingsPage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actorId, setActorIdState] = useState(readActorId);
  const [ready, setReady] = useState(false);

  const setActorId = useCallback((id: string) => {
    const next = id.trim() || 'local';
    writeActorId(next);
    setActorIdState(next);
  }, []);

  const reload = useCallback(() => {
    localApi
      .status()
      .then((data) => {
        setStatus(data);
        setError(null);
      })
      .catch((err: unknown) => {
        setStatus(null);
        setError(err instanceof Error ? err.message : '决策 API 不可达');
      });
  }, []);

  useEffect(() => {
    boot()
      .then(() => {
        setReady(true);
        reload();
      })
      .catch((err: unknown) => {
        setReady(true);
        setError(err instanceof Error ? err.message : '无法启动本地控制台');
      });
  }, [reload]);

  const session = useMemo<LocalSession>(
    () => ({ status, error, actorId, setActorId, reload }),
    [status, error, actorId, setActorId, reload],
  );

  if (!ready) {
    return (
      <div className="content-page">
        <p className="page-desc">正在连接本地决策 API…</p>
      </div>
    );
  }

  return (
    <LocalSessionContext.Provider value={session}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<OverviewPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/agents/:id" element={<AgentDetailPage />} />
          <Route path="/permissions" element={<PermissionsPage />} />
          <Route path="/findings" element={<FindingsPage />} />
          <Route path="/grants" element={<GrantsPage />} />
          <Route path="/receipts" element={<ReceiptsPage />} />
          <Route path="/bindings" element={<BindingsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/inventory" element={<Navigate to="/agents" replace />} />
          <Route path="/admissions" element={<Navigate to="/agents" replace />} />
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Route>
      </Routes>
    </LocalSessionContext.Provider>
  );
}
