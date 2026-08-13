/// <reference types="vite/client" />

/** 控制台环境变量（见 .env.example） */
interface ImportMetaEnv {
  /** 控制面 API 基础地址，默认 http://127.0.0.1:8600/api/v1 */
  readonly VITE_API_BASE?: string;
  /** 开发模式身份注入开关（生产必须为 false） */
  readonly VITE_DEV_MODE?: string;
  /** 开发模式注入的租户（仅 VITE_DEV_MODE=true 生效） */
  readonly VITE_DEV_TENANT_ID?: string;
  /** 开发模式注入的用户（仅 VITE_DEV_MODE=true 生效） */
  readonly VITE_DEV_USER_ID?: string;
  /**
   * 开发模式注入的角色（逗号分隔，仅 VITE_DEV_MODE=true 生效）。
   * 缺省 tenant_admin,security_admin,agent_owner,auditor（覆盖控制台全部视图权限点）。
   */
  readonly VITE_DEV_ROLES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
