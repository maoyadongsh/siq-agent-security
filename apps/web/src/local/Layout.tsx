/** Personal console: four primary workflows, legacy capabilities under advanced navigation. */
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { Icon, type IconName } from '@/components/icons';
import { useLocalSession } from './session';
import { ConfirmationProvider, useConfirmations } from './confirmations';
import { ConfirmationNotificationProvider } from './components/ConfirmationNotifications';
import { platformTierText, hasOpenShellL3 } from './format';
import RawContentStatusIndicator from './components/RawContentStatusIndicator';

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
}

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: '个人管理',
    items: [
      { to: '/agents', label: '我的智能体', icon: 'agents' },
      { to: '/permission-center', label: '权限管理', icon: 'permissions' },
      { to: '/findings', label: '安全中心', icon: 'findings' },
      { to: '/activities', label: '运行审计', icon: 'audit' },
    ],
  },
  {
    label: '高级与设置',
    items: [
      { to: '/confirmations', label: '确认待办', icon: 'shield' },
      { to: '/skill-imports', label: '导入 Skill', icon: 'shield' },
      { to: '/installed-skills', label: '已安装 Skill', icon: 'shield' },
      { to: '/grants', label: '完整授权工作台', icon: 'policies' },
      { to: '/permissions', label: '技术权限事实', icon: 'permissions' },
      { to: '/receipts', label: '回执', icon: 'audit' },
      { to: '/bindings', label: '运行时绑定', icon: 'bindings' },
      { to: '/diagnostics', label: '系统诊断总览', icon: 'overview' },
      { to: '/settings', label: '设置', icon: 'settings' },
    ],
  },
];

const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);

const NAV_COLLAPSED_KEY = 'siq.as.local.nav-collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(NAV_COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

function currentTitle(pathname: string): string {
  if (pathname.startsWith('/activities/')) return '运行详情';
  if (pathname === '/skill-updates') return '更新 Skill';
  if (pathname.startsWith('/agents/')) return '智能体详情';
  const exact = NAV_ITEMS.find((item) => item.to === pathname);
  return exact?.label ?? '总览';
}

export default function Layout() {
  return <ConfirmationProvider><ConfirmationNotificationProvider><LocalLayout /></ConfirmationNotificationProvider></ConfirmationProvider>;
}

function LocalLayout() {
  const location = useLocation();
  const inbox = useConfirmations();
  const pendingCount = inbox.error ? null : inbox.items.filter((item) => item.status === 'pending' && item.expires_at && Date.parse(item.expires_at) > Date.now()).length + inbox.grants.filter((grant) => grant.status === 'pending_approval').length;
  const { status, error, signOut } = useLocalSession();
  const [signingOut, setSigningOut] = useState(false);
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => setOpen(false), [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const toggleCollapsed = () =>
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(NAV_COLLAPSED_KEY, next ? '1' : '0');
      } catch {
        /* ignore */
      }
      return next;
    });

  const badges = (status?.platforms ?? []).filter(
    (p) => p.detected || p.adapter === 'installed',
  );
  const openShellL3 = hasOpenShellL3(status?.platforms);

  return (
    <div className="app-shell local-shell">
      <aside
        aria-label="siq-agent-security 本地导航"
        className={`sidebar siq-glass${collapsed ? ' collapsed' : ''}${open ? ' open' : ''}`}
      >
        <div className="brand">
          <span className="brand-mark">
            <Icon name="shield" size={17} />
          </span>
          <span className="brand-text">
            <span className="brand-title">siq-agent-security</span>
            <span className="brand-sub">本地门禁官 · 单用户</span>
          </span>
        </div>
        <nav className="nav">
          {NAV_GROUPS.map((group, index) => {
            const links = group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                  title={collapsed ? item.label : undefined}
                >
                  <span className="nav-icon" aria-hidden="true">
                    <Icon name={item.icon} />
                  </span>
                  <span className="nav-label">{item.label}{['/confirmations', '/findings'].includes(item.to) && pendingCount !== null && pendingCount > 0 ? `（${pendingCount} 待办）` : ''}</span>
                </NavLink>
              ));
            return index === 0 ? <div className="nav-group" key={group.label}><span className="nav-group-label" aria-hidden={collapsed}>{group.label}</span>{links}</div>
              : <details className="nav-group" key={group.label}><summary className="nav-link" title={group.label}>{collapsed ? '更多' : group.label}</summary>{links}</details>;
          })}
        </nav>
        <div className="sidebar-foot">
          <span className="sidebar-version">
            {status ? `v${status.version} · ${status.enforcement_mode}` : '本地模式'}
          </span>
          <button
            type="button"
            className="nav-collapse-btn"
            onClick={toggleCollapsed}
            aria-label={collapsed ? '展开导航' : '收起导航'}
            aria-expanded={!collapsed}
            title={collapsed ? '展开导航' : '收起导航'}
          >
            <Icon name={collapsed ? 'chevrons-right' : 'chevrons-left'} />
          </button>
        </div>
      </aside>
      {open ? (
        <button type="button" className="nav-overlay" aria-label="关闭导航" onClick={() => setOpen(false)} />
      ) : null}

      <div className="main-col">
        <header className="topbar siq-glass">
          <button type="button" className="hamburger" onClick={() => setOpen(true)} aria-label="打开导航">
            <Icon name="menu" size={20} />
          </button>
          <span className="topbar-title">{currentTitle(location.pathname)}</span>
          <span className="topbar-tags">
            <RawContentStatusIndicator />
            <span className="topbar-phase">
              <span aria-hidden="true" />
              本地模式 · 单用户
            </span>
            {!status ? (
              <span className="topbar-phase">平台探测不可用</span>
            ) : badges.length === 0 ? (
              <span className="topbar-phase">未发现平台</span>
            ) : (
              badges.map((p) => (
                <span key={p.name} className="topbar-phase" title={p.note}>
                  {platformTierText(p, openShellL3)}
                </span>
              ))
            )}
          </span>
          <button type="button" className="btn" disabled={signingOut} onClick={() => {
            setSigningOut(true);
            void signOut().finally(() => setSigningOut(false));
          }}>{signingOut ? '正在退出…' : '退出管理'}</button>
        </header>
        <main className="content">
          {error ? <p className="action-error" role="alert">{error}</p> : null}
          <div key={location.pathname} className="siq-page-enter content-page">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
