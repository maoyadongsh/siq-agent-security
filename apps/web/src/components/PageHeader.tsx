import type { ReactNode } from 'react';
import type { ApiConnectionStatus } from '@/hooks/useApiList';

interface PageHeaderProps {
  title: string;
  description: string;
  /** 控制面连接状态（未连接时展示空态提示） */
  connection?: ApiConnectionStatus;
  /** 连接错误信息 */
  connectionError?: string | null;
  actions?: ReactNode;
}

/**
 * 页头：标题 + 简要说明 + 连接状态徽标 + 可选的页面级操作。
 * 控制面不可用时，各页展示明确连接状态但不阻塞路由渲染。
 */
export default function PageHeader({
  title,
  description,
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
        <span className="page-eyebrow">SIQ AGENT SECURITY</span>
        <h1>{title}</h1>
        <p className="page-desc">{description}</p>
      </div>
      <div className="page-header-right">
        {badge}
        {actions}
      </div>
    </header>
  );
}
