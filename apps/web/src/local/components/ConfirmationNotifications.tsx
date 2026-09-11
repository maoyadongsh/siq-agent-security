import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useConfirmations } from '../confirmations';
import { useLocalSession } from '../session';
import { NOTICE_LIMIT, newNoticeKeys, noticeTargets, readNoticeState } from '../notificationState';

const PREF = 'siq.as.personal.notifications.enabled.v1';
interface Preferences { enabled: boolean; busy: boolean; permission: NotificationPermission | 'unsupported'; error: string | null; toggle: () => Promise<void> }
const Context = createContext<Preferences | null>(null);
function permission(): NotificationPermission | 'unsupported' {
  return typeof Notification !== 'undefined' && window.isSecureContext && navigator.locks ? Notification.permission : 'unsupported';
}
function readEnabled(): boolean {
  try { return localStorage.getItem(PREF) === '1'; } catch { return false; }
}
async function digest(text: string): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, '0')).join('');
}

export function ConfirmationNotificationProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const { status } = useLocalSession();
  const inbox = useConfirmations();
  const [enabled, setEnabled] = useState(readEnabled);
  const [currentPermission, setPermission] = useState(permission);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const notifications = useRef<Notification[]>([]);
  const alive = useRef(false);
  const toggling = useRef(false);
  const preferenceEpoch = useRef(0);
  const close = useCallback(() => {
    for (const notification of notifications.current) { notification.onclick = null; notification.close(); }
    notifications.current = [];
  }, []);
  useEffect(() => {
    alive.current = true;
    const sync = () => { setEnabled(readEnabled()); setPermission(permission()); };
    const changed = (event: StorageEvent) => { if (event.key === PREF || event.key === null) { preferenceEpoch.current += 1; sync(); if (!readEnabled()) close(); } };
    window.addEventListener('storage', changed);
    window.addEventListener('focus', sync);
    return () => { alive.current = false; close(); window.removeEventListener('storage', changed); window.removeEventListener('focus', sync); };
  }, [close]);
  const toggle = useCallback(async () => {
    if (toggling.current) return;
    toggling.current = true;
    const epoch = ++preferenceEpoch.current;
    setBusy(true);
    setError(null);
    try {
      if (readEnabled()) {
        localStorage.setItem(PREF, '0');
        setEnabled(false);
        close();
      } else {
        const available = permission();
        if (available === 'unsupported') throw new Error('当前浏览器不支持此提醒方式，请直接使用确认待办。');
        const granted = available === 'default' ? await Notification.requestPermission() : available;
        if (!alive.current || preferenceEpoch.current !== epoch) return;
        setPermission(granted);
        localStorage.setItem(PREF, granted === 'granted' ? '1' : '0');
        setEnabled(granted === 'granted');
        if (granted !== 'granted') setError('通知未获允许。你仍可在确认待办中处理请求。');
      }
    } catch {
      if (alive.current) setError('暂时无法开启通知。请检查浏览器权限，或直接使用确认待办。');
    } finally {
      toggling.current = false;
      if (alive.current) setBusy(false);
    }
  }, [close]);
  const targets = useMemo(() => noticeTargets(inbox.items, inbox.grants, Date.now()), [inbox.items, inbox.grants]);
  const publicKey = status?.signing_public_key;
  useEffect(() => {
    if (!enabled || permission() !== 'granted' || inbox.error || inbox.loading || !publicKey) { close(); return; }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void navigator.locks.request(`siq-confirmations-${publicKey}`, { ifAvailable: true }, async (lock) => {
        if (!lock || cancelled) return;
        const pending = noticeTargets(inbox.items, inbox.grants, Date.now());
        const selected = pending.length > NOTICE_LIMIT ? [{ key: 'overflow-summary', href: '/confirmations' }] : pending;
        const keys = await Promise.all(selected.map((item) => digest(item.key)));
        if (cancelled || !alive.current || permission() !== 'granted' || !readEnabled()) return;
        const stateKey = `siq.as.personal.notifications.seen.v1.${publicKey}`;
        const prior = localStorage.getItem(stateKey);
        const previous = readNoticeState(prior);
        const now = Date.now();
        const fresh = newNoticeKeys(keys, previous, now);
        if (!fresh.length) {
          if (!keys.length) close();
          // Drop completed requests without resetting the rate-limit clock.
          if (keys.every((key) => previous.keys.includes(key))) localStorage.setItem(stateKey, JSON.stringify({ keys, sentAt: previous.sentAt }));
          return;
        }
        const href = fresh.length === 1 ? selected[keys.indexOf(fresh[0])].href : '/confirmations';
        // Prove metadata storage works before emitting; roll back if construction fails.
        localStorage.setItem(stateKey, JSON.stringify({ keys, sentAt: now }));
        try {
          const notification = new Notification('SIQ 有新的确认待办', {
            body: `当前有 ${pending.length} 项待审阅请求。点击打开 SIQ 查看。`,
            tag: `siq-confirmations-${publicKey}`,
          });
          close();
          notifications.current = [notification];
          notification.onerror = () => { if (alive.current) setError('系统未能显示通知，请在确认待办中查看请求。'); };
          notification.onclick = () => {
            if (!alive.current) return;
            window.focus();
            navigate(href);
            close();
          };
          if (alive.current) setError(null);
        } catch {
          if (prior === null) localStorage.removeItem(stateKey); else localStorage.setItem(stateKey, prior);
          throw new Error('notification unavailable');
        }
      }).catch(() => { if (!cancelled && alive.current) setError('通知暂不可用，请在确认待办中查看请求。'); });
    }, 500);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [enabled, currentPermission, publicKey, targets, inbox.items, inbox.grants, inbox.error, inbox.loading, navigate, close]);
  const value = useMemo(() => ({ enabled, permission: currentPermission, busy, error, toggle }), [enabled, currentPermission, busy, error, toggle]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function NotificationPreferences() {
  const state = useContext(Context);
  if (!state) return null;
  return <div className="card">
    <h2>待办提醒</h2>
    <p className="page-desc">开启后，SIQ 会通过浏览器合并提醒新的待办；通知不显示操作内容。请保持管理页面打开，后台提醒可能延迟。</p>
    <button type="button" className="btn" disabled={state.busy || (state.permission === 'unsupported' && !state.enabled)} onClick={() => void state.toggle()}>
      {state.busy ? '正在设置通知…' : state.enabled ? '关闭通知' : '开启通知'}
    </button>
    <p role="status">{state.error ?? (state.permission === 'unsupported' ? '当前浏览器不支持此提醒方式，确认待办仍可使用。'
      : state.permission === 'denied' ? '浏览器已拒绝通知，确认待办仍可使用。'
      : state.enabled ? '浏览器提醒已开启。点击通知只打开详情，不会批准请求。' : '提醒默认关闭，你可以随时在这里开启。')}</p>
  </div>;
}
