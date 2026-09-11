import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './Layout';
const SkillUpdatesPage = lazy(() => import('./pages/SkillUpdatesPage'));
const InstalledSkillsPage = lazy(() => import('./pages/InstalledSkillsPage'));
const SkillImportsPage = lazy(() => import('./pages/SkillImportsPage'));
import { Icon } from '@/components/icons';
import { boot, localApi, pair, restoreSession, logout, onSessionExpired, LocalApiError } from './api';
import { LocalSessionContext, readActorId, writeActorId, type LocalSession } from './session';
import type { Status } from './types';
import OverviewPage from './pages/OverviewPage';
import AgentsPage from './pages/AgentsPage';
import AgentDetailPage from './pages/AgentDetailPage';
import PermissionsPage from './pages/PermissionsPage';
import FindingsPage from './pages/FindingsPage';
import GrantsPage from './pages/GrantsPage';
import ConfirmationsPage from './pages/ConfirmationsPage';
import ReceiptsPage from './pages/ReceiptsPage';
import BindingsPage from './pages/BindingsPage';
import SettingsPage from './pages/SettingsPage';

const DemoPage = lazy(() => import('./pages/DemoPage'));

export default function App() {
  return <Routes>
    <Route path="/demo" element={<Suspense fallback={<p>正在载入比赛演示…</p>}><DemoPage /></Suspense>} />
    <Route path="*" element={<LocalAdminApp />} />
  </Routes>;
}

function LocalAdminApp() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actorId, setActorIdState] = useState(readActorId);
  const [ready, setReady] = useState(false);
  const [needsPairing, setNeedsPairing] = useState(false);
  const [pairingCode, setPairingCode] = useState('');
  const [pairingBusy, setPairingBusy] = useState(false);
  const [bootFailed, setBootFailed] = useState(false);
  const [bootAttempt, setBootAttempt] = useState(0);

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
          setError('管理会话已失效。请运行 siq-agent-security pair 获取新配对码，无需重启服务。');
          return;
        }
        setError(err instanceof Error ? err.message : '决策 API 不可达');
      });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setReady(false);
    setBootFailed(false);
    setError(null);
    boot().then(async (cfg) => cfg.session_recovery && await restoreSession())
      .then((restored) => {
        if (cancelled) return;
        setNeedsPairing(!restored);
        setReady(true);
        if (restored) reload();
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setReady(true);
        setBootFailed(true);
        setError(err instanceof Error ? err.message : '无法启动本地控制台');
      });
    return () => { cancelled = true; };
  }, [reload, bootAttempt]);

  useEffect(() => onSessionExpired(() => {
    setStatus(null);
    setNeedsPairing(true);
    setError('管理会话已失效。请运行 siq-agent-security pair 获取新配对码。');
  }), []);

  const signOut = useCallback(async () => {
    try {
      await logout();
      setStatus(null);
      setError(null);
      setNeedsPairing(true);
      setPairingCode('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '退出失败，请重试');
    }
  }, []);

  const submitPairing = (event: FormEvent) => {
    event.preventDefault();
    setPairingBusy(true);
    setError(null);
    pair(pairingCode)
      .then(() => {
        setPairingCode('');
        setNeedsPairing(false);
        reload();
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '配对失败');
      })
      .finally(() => setPairingBusy(false));
  };

  const session = useMemo<LocalSession>(
    () => ({ status, error, actorId, setActorId, reload, signOut }),
    [status, error, actorId, setActorId, reload, signOut],
  );

  if (!ready) {
    return (
      <div className="auth-boot">
        <div className="auth-boot-inner">
          <span className="icon-spin" aria-hidden="true">
            <Icon name="loading" size={18} />
          </span>
          正在连接本地服务…
        </div>
      </div>
    );
  }

  if (bootFailed) {
    return <main className="login-shell"><section className="login-card">
      <h1>暂时无法打开本地管理</h1>
      <p className="login-desc" role="alert">{error}</p>
      <p className="login-desc">运行 <code>siq-agent-security status</code> 检查服务；尚未启动时，运行 <code>siq-agent-security serve</code>。</p>
      <button type="button" className="btn btn-primary" onClick={() => setBootAttempt((attempt) => attempt + 1)}>重新连接</button>
    </section></main>;
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
            <h1>连接你的本地管理台</h1>
            <p className="login-desc">
              输入启动服务时显示的配对码，或运行 <span className="mono">siq-agent-security pair</span> 获取新码。
              配对码 5 分钟内单次有效。配对后可在 12 小时内刷新页面继续使用；服务重启后需重新配对。
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
          <details className="login-desc"><summary>本机安全边界</summary>
            同一系统用户下的进程可能读取本地状态或执行 CLI。管理配对隔离浏览器访问与智能体决策接口；更强的进程隔离需相应运行环境支持。
          </details>
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
          <Route path="/confirmations" element={<ConfirmationsPage />} />
          <Route path="/skill-updates" element={<Suspense fallback={<p role="status">正在打开 Skill 更新…</p>}><SkillUpdatesPage /></Suspense>} />
          <Route path="/installed-skills" element={<Suspense fallback={<p role="status">正在打开安装记录…</p>}><InstalledSkillsPage /></Suspense>} />
          <Route path="/skill-imports" element={<Suspense fallback={<p role="status">正在打开 Skill 导入…</p>}><SkillImportsPage /></Suspense>} />
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
