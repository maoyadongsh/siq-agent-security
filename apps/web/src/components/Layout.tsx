/** 应用外壳（对齐 SIQ 工作台布局语言：浅色磨砂侧栏 + 顶栏 + 独立滚动内容区）。
 * 桌面端侧边栏支持 展开（图标+文字）/ 收起（仅图标 + tooltip），选择持久化
 * localStorage（非敏感 UI 偏好）；移动端 <768px 为抽屉导航。 */
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { Icon, type IconName } from '@/components/icons';

/** 侧边导航项（对齐设计文档 §20.1 信息架构） */
const NAV_ITEMS: { to: string; label: string; icon: IconName }[] = [
  { to: '/overview', label: '总览', icon: 'overview' },
  { to: '/agents', label: '智能体资产', icon: 'agents' },
  { to: '/permissions', label: '权限视图', icon: 'permissions' },
  { to: '/findings', label: '风险中心', icon: 'findings' },
  { to: '/policies', label: '策略中心', icon: 'policies' },
  { to: '/changes', label: '变更中心', icon: 'changes' },
  { to: '/runtime-bindings', label: '运行时绑定', icon: 'bindings' },
  { to: '/environments', label: '环境与 Connector', icon: 'environments' },
  { to: '/audit', label: '审计', icon: 'audit' },
  { to: '/settings', label: '设置', icon: 'settings' },
];

/** 非敏感 UI 偏好：侧边栏收起状态（版本化前缀 siq.as.*） */
const NAV_COLLAPSED_KEY = 'siq.as.nav-collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(NAV_COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

/** 由当前路径推导顶栏标题（详情页回落到所属列表页） */
function currentTitle(pathname: string): string {
  const exact = NAV_ITEMS.find((item) => item.to === pathname);
  if (exact) return exact.label;
  const prefix = NAV_ITEMS.find(
    (item) => item.to !== '/overview' && pathname.startsWith(`${item.to}/`),
  );
  return prefix?.label ?? '总览';
}

export default function Layout() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => setOpen(false), [location.pathname, location.search]);

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
          <span className="topbar-title">{currentTitle(location.pathname)}</span>
          <span className="topbar-phase"><span aria-hidden="true" />证据优先 · 安全控制面</span>
        </header>
        <main className="content">
          {/* key 驱动换页入场动画 */}
          <div key={`${location.pathname}${location.search}`} className="siq-page-enter content-page">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
