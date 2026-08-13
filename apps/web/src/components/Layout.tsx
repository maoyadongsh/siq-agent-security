import { NavLink, Outlet } from 'react-router-dom';

/** 侧边导航项（对齐设计文档 §20.1 信息架构） */
const NAV_ITEMS = [
  { to: '/overview', label: '总览', icon: '◈' },
  { to: '/agents', label: '智能体资产', icon: '◉' },
  { to: '/permissions', label: '权限视图', icon: '◎' },
  { to: '/findings', label: '风险中心', icon: '⚠' },
  { to: '/policies', label: '策略中心', icon: '▣' },
  { to: '/changes', label: '变更中心', icon: '⇄' },
  { to: '/environments', label: '环境与 Connector', icon: '▤' },
  { to: '/audit', label: '审计', icon: '✎' },
  { to: '/settings', label: '设置', icon: '⚙' },
];

export default function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">SIQ</span>
          <span className="brand-title">Agent Security</span>
        </div>
        <nav className="nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
            >
              <span className="nav-icon" aria-hidden="true">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">Phase 1 · 骨架</div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
