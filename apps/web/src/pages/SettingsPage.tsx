import PageHeader from '@/components/PageHeader';
import { API_BASE } from '@/api/client';

/**
 * 设置（Phase 1 占位）：展示连接配置与安全不变量说明。
 * 认证流程（登录/刷新）在 Phase 2 接入；届时 token 仍只允许驻留内存。
 */
export default function SettingsPage() {
  const devMode = import.meta.env.VITE_DEV_MODE === 'true';

  return (
    <section>
      <PageHeader
        title="设置"
        description="控制台连接与认证配置（Phase 1 只读展示；Phase 2 接入真实登录与租户切换）。"
        connection="disconnected"
        connectionError="设置数据接口尚未联调"
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
        <h2>安全不变量</h2>
        <ul className="page-desc">
          <li>
            <strong>token 不落 localStorage</strong>：Bearer token 仅保存在内存
            （src/api/client.ts 的 setToken），页面刷新即失效，与 SIQ 平台安全不变量一致；
          </li>
          <li>
            开发/演示环境仅通过 X-Dev-Tenant-Id / X-Dev-User-Id 头注入身份，
            由 VITE_DEV_MODE 开关控制；
          </li>
          <li>
            401 处理为占位（client.onUnauthorized），Phase 2 接入刷新 / 重定向登录流程。
          </li>
        </ul>
      </div>
    </section>
  );
}
