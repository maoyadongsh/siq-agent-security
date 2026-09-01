/**
 * "未连接"空态：控制面 API 不可达时展示，标注 placeholder 数据来源，
 * 并给出重试入口 —— 不阻塞页面与构建（Phase 1 后端未联调）。
 */
import type { ReactNode } from 'react';

interface DisconnectedNoticeProps {
  error?: string | null;
  /** 说明数据为本地占位 */
  children?: ReactNode;
  onRetry?: () => void;
}

export default function DisconnectedNotice({
  error,
  children,
  onRetry,
}: DisconnectedNoticeProps) {
  return (
    <div className="notice" role="status">
      <p className="notice-title">
        未连接 — 控制面暂不可达，以下展示安全示例数据
      </p>
      {error ? <p className="notice-detail">{error}</p> : null}
      {children ? <p className="notice-detail">{children}</p> : null}
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          重试连接
        </button>
      ) : null}
    </div>
  );
}
