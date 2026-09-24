import { Link } from 'react-router-dom';
import { useConsoleContext } from '@/components/ConsoleContext';
import { useEffect, useState } from 'react';

import PageHeader from '@/components/PageHeader';
import { API_BASE } from '@/api/client';
import type { ApiConnectionStatus } from '@/hooks/useApiList';

/**
 * 设置：展示连接配置与安全不变量说明。
 * 连接状态徽标来自控制面 API `/health` 实时探测；
 * 平台嵌入时走 IAM 会话；token 仍只允许驻留内存。
 */
export default function SettingsPage() {
  const { data } = useConsoleContext();
  const [connection, setConnection] = useState<ApiConnectionStatus>('loading');
  const [connectionError, setConnectionError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/health`, { headers: { Accept: 'application/json' } })
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
        icon="settings"
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
        <p>当前组织：{data?.tenant.name || '尚未核对名称'}。身份与权限以服务端读回为准。</p>
        <p><Link to="/workspace">查看组织与角色</Link></p>
      </div>
      <div className="card">
        <h2>会话安全边界</h2>
        <ul className="page-desc">
          <li>
            <strong>访问凭证不写入浏览器长期存储</strong>：凭证仅保留在内存中；刷新页面后，通过现有 IAM 会话重新获取；
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
