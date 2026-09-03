import { useState, type FormEvent } from 'react';

import { loginWithPassword } from '@/api/session';
import { Icon } from '@/components/icons';

export default function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await loginWithPassword(username, password);
      onSuccess();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="login-brand">
          <span className="brand-mark">
            <Icon name="shield" size={20} />
          </span>
          <div className="login-brand-text">
            <p className="login-brand-title">Agent Security</p>
            <p className="login-brand-sub">SIQ 智能体安全管控平台</p>
          </div>
        </div>
        <div className="login-intro">
          <p className="kicker">
            <Icon name="shield" size={14} />
            安全登录
          </p>
          <h1>欢迎回来</h1>
          <p className="login-desc">使用已授权的账户访问智能体安全控制台</p>
        </div>
        <form className="login-form" onSubmit={submit} noValidate>
          <label className="login-field">
            用户名
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </label>
          <label className="login-field">
            密码
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error ? (
            <p role="alert" className="action-error">
              {error}
            </p>
          ) : null}
          <button type="submit" className="btn btn-primary login-submit" disabled={submitting}>
            {submitting ? '登录中…' : '登录'}
          </button>
        </form>
      </section>
    </main>
  );
}
