import type { ReactNode } from 'react';
import { Icon, type IconName } from '@/components/icons';
import type { ApiConnectionStatus } from '@/hooks/useApiList';

interface PageHeaderProps {
  title: string;
  description: string;
  /** kicker 眉题胶囊图标（默认盾牌，页面对齐各自导航图标） */
  icon?: IconName;
  /** 控制面连接状态（未连接时展示空态提示） */
  connection?: ApiConnectionStatus;
  /** 连接错误信息 */
  connectionError?: string | null;
  actions?: ReactNode;
}

/**
 * 页头三件套：hero 面板内 kicker（图标 + 金边胶囊）→ h1 流体字 → 13px muted 描述，
 * 右侧连接状态徽标与页面级操作。控制面不可用时展示明确状态但不阻塞路由渲染。
 */
export default function PageHeader({
  title,
  description,
  icon = 'shield',
  connection = 'loading',
  connectionError = null,
  actions,
}: PageHeaderProps) {
  let badge: ReactNode;
  if (connection === 'connected') {
    badge = <span className="badge badge-ok">已连接</span>;
  } else if (connection === 'loading') {
    badge = <span className="badge badge-pending">连接中…</span>;
  } else {
    badge = (
      <span className="badge badge-off" title={connectionError ?? undefined}>
        未连接
      </span>
    );
  }

  return (
    <header className="page-header">
      <div className="page-header-copy">
        <span className="kicker">
          <Icon name={icon} size={14} />
          SIQ AGENT SECURITY
        </span>
        <h1>{title}</h1>
      </div>
      <div className="page-header-right">
        {badge}
        {actions}
      </div>
      <p className="page-desc">{description}</p>
    </header>
  );
}
