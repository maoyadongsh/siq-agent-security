/**
 * 平台嵌入时用 IAM HttpOnly refresh cookie 或账号密码换取内存 access token。
 * 独立开发（VITE_DEV_MODE）不走这条路径。
 */

import { onUnauthorized, setToken } from './client';

const IAM_BASE = import.meta.env.VITE_IAM_URL ?? '/api/iam';
const DEV_MODE = import.meta.env.VITE_DEV_MODE === 'true';

export function registerUnauthorizedHandler(handler: () => void): void {
  onUnauthorized(handler);
}

export async function restoreSession(): Promise<boolean> {
  if (DEV_MODE) return true;
  try {
    const response = await fetch(`${IAM_BASE}/api/v1/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
      signal: AbortSignal.timeout(30_000),
    });
    if (!response.ok) return false;
    const payload = (await response.json()) as { access_token?: string };
    if (!payload.access_token) return false;
    setToken(payload.access_token);
    return true;
  } catch {
    return false;
  }
}

function messageFromLoginFailure(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback;
  const data = payload as Record<string, unknown>;
  const nested = data.error;
  if (nested && typeof nested === 'object') {
    const message = (nested as Record<string, unknown>).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  const detail = data.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail[0] && typeof detail[0] === 'object') {
    const first = detail[0] as Record<string, unknown>;
    if (typeof first.msg === 'string' && first.msg.trim()) return first.msg;
  }
  return fallback;
}

export async function loginWithPassword(username: string, password: string): Promise<void> {
  const response = await fetch(`${IAM_BASE}/api/v1/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    let message = '登录失败';
    try {
      message = messageFromLoginFailure(await response.json(), message);
    } catch {
      /* keep fallback */
    }
    throw new Error(message);
  }
  const payload = (await response.json()) as { access_token?: string };
  if (!payload.access_token) {
    throw new Error('登录响应缺少 access token');
  }
  setToken(payload.access_token);
}
