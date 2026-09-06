import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './Layout';
import { Icon } from '@/components/icons';
import { boot, localApi, pair, LocalApiError } from './api';
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
  const [needsPairing, setNeedsPairing] = useState(false);
  const [pairingCode, setPairingCode] = useState('');
  const [pairingBusy, setPairingBusy] = useState(false);

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
        if (err instanceof LocalApiError && err.status === 401) {
          setNeedsPairing(true);
          setError('管理会话仅保存在本页内存。刷新后请重启 serve 以获取新的配对码。');
          return;
        }
        setError(err instanceof Error ? err.message : '决策 API 不可达');
      });
  }, []);

  useEffect(() => {
    boot()
      .then((cfg) => {
        setNeedsPairing(Boolean(cfg.pairing_required));
        setReady(true);
        if (!cfg.pairing_required) {
          reload();
        }
      })
      .catch((err: unknown) => {
        setReady(true);
        setError(err instanceof Error ? err.message : '无法启动本地控制台');
      });
  }, [reload]);

  const submitPairing = (event: FormEvent) => {
    event.preventDefault();
    setPairingBusy(true);
    setError(null);
    pair(pairingCode)
      .then(() => {
        setNeedsPairing(false);
        reload();
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '配对失败');
      })
      .finally(() => setPairingBusy(false));
  };

  const session = useMemo<LocalSession>(
    () => ({ status, error, actorId, setActorId, reload }),
    [status, error, actorId, setActorId, reload],
  );

  if (!ready) {
    return (
      <div className="auth-boot">
        <div className="auth-boot-inner">
          <span className="icon-spin" aria-hidden="true">
            <Icon name="loading" size={18} />
          </span>
          正在连接本地决策 API…
        </div>
      </div>
    );
  }

  if (needsPairing) {
    return (
      <main className="login-shell">
        <section className="login-card">
          <div className="login-brand">
            <span className="brand-mark">
              <Icon name="shield" size={20} />
            </span>
            <div className="login-brand-text">
              <p className="login-brand-title">siq-agent-security</p>
              <p className="login-brand-sub">本地模式 · 单用户</p>
            </div>
          </div>
          <div className="login-intro">
            <p className="kicker">
              <Icon name="shield" size={14} />
              管理配对
            </p>
            <h1>输入启动配对码</h1>
            <p className="login-desc">
              配对码打印在 <span className="mono">siq-agent-security serve</span> 的终端上，5
              分钟内单次有效。同 UID 进程仍可读状态目录；这不能防止被注入的 Agent 直接执行
              CLI。
            </p>
          </div>
          <form className="login-form" onSubmit={submitPairing}>
            <label className="login-field">
              配对码
              <input
                autoComplete="one-time-code"
                value={pairingCode}
                onChange={(event) => setPairingCode(event.target.value)}
                placeholder="xxxx-xxxx-xxxx-xxxx"
                required
              />
            </label>
            {error ? (
              <p role="alert" className="action-error">
                {error}
              </p>
            ) : null}
            <button type="submit" className="btn btn-primary login-submit" disabled={pairingBusy}>
              {pairingBusy ? '配对中…' : '建立管理会话'}
            </button>
          </form>
        </section>
      </main>
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
