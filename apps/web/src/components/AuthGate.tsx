import { useEffect, useState, type ReactNode } from 'react';

import { registerUnauthorizedHandler, restoreSession } from '@/api/session';
import { Icon } from '@/components/icons';
import LoginPage from '@/pages/LoginPage';

const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true';

/**
 * 平台嵌入：先尝试 IAM refresh cookie，没有会话则展示本控制台登录页。
 * 独立开发（VITE_DEV_MODE）跳过，继续走 X-Dev-* 身份头。
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<'boot' | 'login' | 'ready'>(DEV_MODE ? 'ready' : 'boot');

  useEffect(() => {
    if (DEV_MODE) return undefined;
    registerUnauthorizedHandler(() => setPhase('login'));
    void restoreSession().then((ok) => setPhase(ok ? 'ready' : 'login'));
    return undefined;
  }, []);

  if (phase === 'boot') {
    return (
      <main className="auth-boot">
        <p className="auth-boot-inner">
          <Icon name="loading" size={16} className="icon-spin" />
          正在恢复会话
        </p>
      </main>
    );
  }
  if (phase === 'login') {
    return <LoginPage onSuccess={() => setPhase('ready')} />;
  }
  return children;
}
