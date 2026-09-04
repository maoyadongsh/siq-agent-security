/** 本地模式外壳：复用企业控制台 Layout 语言，导航换成 AgentShield 五页。 */
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { Icon, type IconName } from '@/components/icons';
import { useLocalSession } from './session';
import { platformLabel } from './format';

const NAV_ITEMS: { to: string; label: string; icon: IconName }[] = [
  { to: '/overview', label: '总览', icon: 'overview' },
  { to: '/inventory', label: '盘点', icon: 'scan' },
  { to: '/admissions', label: '准入', icon: 'findings' },
  { to: '/grants', label: '签发', icon: 'permissions' },
  { to: '/receipts', label: '回执', icon: 'audit' },
  { to: '/settings', label: '设置', icon: 'settings' },
];

const NAV_COLLAPSED_KEY = 'siq.as.local.nav-collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(NAV_COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

function currentTitle(pathname: string): string {
  const exact = NAV_ITEMS.find((item) => item.to === pathname);
  return exact?.label ?? '总览';
}

export default function Layout() {
  const location = useLocation();
  const { status } = useLocalSession();
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

  return (
    <div className="app-shell">
      <aside
        aria-label="AgentShield 本地导航"
        className={`sidebar siq-glass${collapsed ? ' collapsed' : ''}${open ? ' open' : ''}`}
      >
        <div className="brand">
          <span className="brand-mark">
            <Icon name="shield" size={17} />
          </span>
          <span className="brand-text">
            <span className="brand-title">AgentShield</span>
            <span className="brand-sub">本地门禁官 · 单用户</span>
          </span>
        </div>
        <nav className="nav">
          {NAV_ITEMS.map((item) => (
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
              <span className="nav-label">{item.label}</span>
            </NavLink>
          ))}
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
            <span className="topbar-phase">
              <span aria-hidden="true" />
              本地模式 · 单用户
            </span>
            {badges.length === 0 ? (
              <span className="topbar-phase">未发现平台</span>
            ) : (
              badges.map((p) => (
                <span key={p.name} className="topbar-phase" title={p.note}>
                  {platformLabel(p.name)} · {p.tier}
                </span>
              ))
            )}
          </span>
        </header>
        <main className="content">
          <div key={location.pathname} className="siq-page-enter content-page">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
