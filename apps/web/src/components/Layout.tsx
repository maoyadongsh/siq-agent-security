/** 应用外壳（对齐 SIQ 工作台布局语言：浅色磨砂侧栏 + 顶栏 + 独立滚动内容区）。
 * 桌面端侧边栏支持 展开（图标+文字）/ 收起（仅图标 + tooltip），选择持久化
 * localStorage（非敏感 UI 偏好）；移动端 <768px 为抽屉导航。
 * 企业端导航（ENT-018 子任务）：四主入口（资产/权限/安全/审计）+ 默认折叠的
 * "管理与高级功能"次级区域；位于次级页面时自动展开（不改变浏览器 URL）。 */
import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useConsoleContext } from '@/components/ConsoleContext';
import { canVisit, routeAccessKey } from '@/api/consoleContext';
import { Icon } from '@/components/icons';
import {
  ADVANCED_GROUP_LABEL,
  ADVANCED_NAV_ITEMS,
  MAIN_NAV_ITEMS,
  enterpriseTitle,
  filterByAccess,
  isAdvancedPath,
  type EnterpriseNavItem,
} from '@/components/enterpriseNav';
import './enterprise-nav.css';

/** 非敏感 UI 偏好：侧边栏收起状态（版本化前缀 siq.as.*） */
const NAV_COLLAPSED_KEY = 'siq.as.nav-collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(NAV_COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

function NavEntry({ item, collapsed, onNavigate }: { item: EnterpriseNavItem; collapsed: boolean; onNavigate: () => void }) {
  return (
    <NavLink
      to={item.to}
      end={item.to !== '/agents'}
      onClick={onNavigate}
      className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
      title={collapsed ? item.label : undefined}
    >
      <span className="nav-icon" aria-hidden="true">
        <Icon name={item.icon} />
      </span>
      <span className="nav-label">{item.label}</span>
    </NavLink>
  );
}

export default function Layout() {
  const location = useLocation();
  const context = useConsoleContext();
  const mainItems = filterByAccess(MAIN_NAV_ITEMS, context.data);
  const advancedItems = filterByAccess(ADVANCED_NAV_ITEMS, context.data);
  const accessible = !routeAccessKey(location.pathname) || canVisit(context.data, location.pathname);
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  // null = 跟随路径自动展开；用户手动切换后以用户选择为准，导航变化时恢复自动。
  const [advancedOverride, setAdvancedOverride] = useState<boolean | null>(null);
  const advancedOpen = advancedOverride ?? isAdvancedPath(location.pathname);

  useEffect(() => setOpen(false), [location.pathname, location.search]);
  useEffect(() => setAdvancedOverride(null), [location.pathname]);

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
        /* 写入失败（如隐私模式）时仅本次会话生效 */
      }
      return next;
    });

  return (
    <div className="app-shell">
      {/* 侧边导航 */}
      <aside
        aria-label="SIQ 智能体安全导航"
        className={`sidebar siq-glass${collapsed ? ' collapsed' : ''}${open ? ' open' : ''}`}
      >
        <div className="brand">
          <span className="brand-mark">
            <Icon name="shield" size={17} />
          </span>
          <span className="brand-text">
            <span className="brand-title">Agent Security</span>
            <span className="brand-sub">SIQ 智能体安全管控</span>
          </span>
        </div>
        <nav className="nav">
          <div className="nav-group entnav-main">
            {mainItems.map((item) => (
              <NavEntry key={item.to} item={item} collapsed={collapsed} onNavigate={() => setOpen(false)} />
            ))}
          </div>
          {advancedItems.length > 0 ? (
            <div className="nav-group entnav-advanced">
              <button
                type="button"
                className={`nav-link entnav-advanced-toggle${advancedOpen ? ' is-open' : ''}`}
                aria-expanded={advancedOpen}
                aria-controls="entnav-advanced-items"
                onClick={() => setAdvancedOverride(!advancedOpen)}
                title={collapsed ? ADVANCED_GROUP_LABEL : undefined}
              >
                <span className="nav-icon" aria-hidden="true">
                  <Icon name="activity" />
                </span>
                <span className="nav-label">{ADVANCED_GROUP_LABEL}</span>
                <span className="entnav-chev" aria-hidden="true">
                  <Icon name="chevron-right" size={14} />
                </span>
              </button>
              {advancedOpen ? (
                <div id="entnav-advanced-items" className="entnav-advanced-items">
                  {advancedItems.map((item) => (
                    <NavEntry key={item.to} item={item} collapsed={collapsed} onNavigate={() => setOpen(false)} />
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </nav>
        <div className="sidebar-foot">
          <span className="sidebar-version">Evidence-first control plane</span>
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
        <button
          type="button"
          className="nav-overlay"
          aria-label="关闭导航"
          onClick={() => setOpen(false)}
        />
      ) : null}

      {/* 主区域 */}
      <div className="main-col">
        <header className="topbar siq-glass">
          <button
            type="button"
            className="hamburger"
            onClick={() => setOpen(true)}
            aria-label="打开导航"
          >
            <Icon name="menu" size={20} />
          </button>
          <span className="topbar-title">{enterpriseTitle(location.pathname)}</span>
          <Link className="topbar-phase" to="/workspace">组织与权限</Link>
        </header>
        <main className="content">
          {/* 同页查询参数由页面处理；弹窗开关不能清掉未确认写入的恢复状态。 */}
          <div key={location.pathname} className="siq-page-enter content-page">
            {accessible ? <Outlet /> : context.status === 'loading' ? <p role="status">正在核对页面访问权限…</p>
              : context.status === 'error' ? <section className="card"><h1>暂时无法核对访问权限</h1><p role="alert">请重试，当前不显示旧身份的业务页面。</p><button className="btn" onClick={context.reload}>重新核对权限</button><p><Link to="/workspace">返回工作台</Link></p></section>
                : <section className="card"><h1>当前账号无法访问此页面</h1><p>请联系所属组织管理员，说明需要访问的功能和用途。后端仍会独立检查每次请求。</p><Link to="/workspace">查看我的组织与权限</Link></section>}
          </div>
        </main>
      </div>
    </div>
  );
}
