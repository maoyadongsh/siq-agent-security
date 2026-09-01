import { useEffect, useState } from 'react';

import PageHeader from '@/components/PageHeader';
import { API_BASE } from '@/api/client';
import type { ApiConnectionStatus } from '@/hooks/useApiList';

/**
 * 设置：展示连接配置与安全不变量说明。
 * 连接状态徽标来自控制面 /health 实时探测（vite proxy 已转发 /health）；
 * 认证流程（登录/刷新）在 Phase 2 接入；届时 token 仍只允许驻留内存。
 */
export default function SettingsPage() {
  const devMode = import.meta.env.VITE_DEV_MODE === 'true';
  const [connection, setConnection] = useState<ApiConnectionStatus>('loading');
  const [connectionError, setConnectionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/health', { headers: { Accept: 'application/json' } })
      .then((resp) => {
        if (cancelled) return;
        if (resp.ok) {
          setConnection('connected');
        } else {
          setConnection('disconnected');
          setConnectionError(`健康检查返回 HTTP ${resp.status}`);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setConnection('disconnected');
        setConnectionError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section>
      <PageHeader
        title="设置"
        description="查看控制面连接状态、运行环境与当前会话的安全边界。"
        connection={connection}
        connectionError={connectionError}
      />
      <div className="card">
        <h2>连接配置</h2>
        <div className="field">
          <label htmlFor="api-base">控制面 API 基础地址（VITE_API_BASE）</label>
          <input id="api-base" type="text" value={API_BASE} readOnly disabled />
        </div>
        <div className="field">
          <label htmlFor="dev-mode">开发模式身份注入（VITE_DEV_MODE）</label>
          <input
            id="dev-mode"
            type="text"
            value={`${devMode}${devMode ? ` · tenant=${import.meta.env.VITE_DEV_TENANT_ID ?? '(未设置)'} · user=${import.meta.env.VITE_DEV_USER_ID ?? '(未设置)'}` : ''}`}
            readOnly
            disabled
          />
        </div>
        <p className="page-desc">
          开发身份注入默认关闭；只有显式设置 VITE_DEV_MODE=true 才会发送 X-Dev-* 头。
        </p>
      </div>
      <div className="card">
        <h2>会话安全边界</h2>
        <ul className="page-desc">
          <li>
            <strong>访问凭证不写入浏览器长期存储</strong>：凭证仅保留在当前页面会话内，刷新后即失效；
          </li>
          <li>
            开发身份模拟默认关闭，只有显式启用开发模式后才会附加租户与用户标识；
          </li>
          <li>
            认证失效时会立即清除会话凭证，避免失效身份继续访问控制面。
          </li>
        </ul>
      </div>
    </section>
  );
}
