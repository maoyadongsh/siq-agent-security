import { useEffect, useRef, useState } from 'react';
import { beginBrowserConnection, type BrowserConnection } from '../api';

export default function BrowserConnect({ onConnected }: { onConnected: () => void }) {
  const [request, setRequest] = useState<{ id: string; deadline: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const operation = useRef<BrowserConnection | null>(null);
  const generation = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const mounted = useRef(false);
  const pending = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      ++generation.current;
      clearTimeout(timer.current);
      void operation.current?.cancel().catch(() => {});
    };
  }, []);

  async function begin() {
    if (pending.current || operation.current) return;
    pending.current = true;
    const attempt = ++generation.current;
    setBusy(true); setError(''); setCopied(false);
    try {
      const connection = await beginBrowserConnection();
      if (!mounted.current || attempt !== generation.current) { await connection.cancel(); return; }
      operation.current = connection;
      const deadline = Date.now() + connection.expiresIn * 1000;
      setRequest({ id: connection.requestId, deadline });
      setSeconds(connection.expiresIn);
      const poll = async () => {
        if (!mounted.current || attempt !== generation.current) return;
        const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        setSeconds(remaining);
        try {
          if (!remaining) throw new Error('连接请求已过期，请重新发起。');
          if (await connection.poll()) {
            if (mounted.current && attempt === generation.current) { operation.current = null; onConnected(); }
            return;
          }
          if (mounted.current && attempt === generation.current) timer.current = setTimeout(poll, 1500);
        } catch (err) {
          if (mounted.current && attempt === generation.current) {
            setError(err instanceof Error ? err.message : '连接失败，请重试。');
            setRequest(null); operation.current = null;
            void connection.cancel().catch(() => {});
          }
        }
      };
      timer.current = setTimeout(poll, 1000);
    } catch (err) {
      if (mounted.current && attempt === generation.current) setError(err instanceof Error ? err.message : '无法连接，请使用手动配对。');
    } finally {
      pending.current = false;
      if (mounted.current && attempt === generation.current) setBusy(false);
    }
  }

  async function cancel() {
    ++generation.current;
    clearTimeout(timer.current);
    const connection = operation.current;
    operation.current = null; setRequest(null); setBusy(true); setCopied(false);
    try { await connection?.cancel(); }
    catch { if (mounted.current) setError('取消尚未确认；不要批准旧请求，它会在五分钟内失效。'); }
    finally { if (mounted.current) setBusy(false); }
  }

  const prompt = request ? `请使用本机已安装的 SIQ Agent Security Skill，确认连接我的个人管理台浏览器。请求编号：${request.id}。仅确认此浏览器管理会话，不批准任何智能体业务权限。` : '';
  return <section aria-label="通过智能体连接">
    <p className="login-desc">已通过 Skill 安装？无需找终端或配对码：发起连接，把下面的请求发给同一台设备上的智能体，确认后此页面自动进入。</p>
    {!request ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void begin()}>{busy ? '正在准备…' : '通过智能体连接'}</button> : <>
      <label className="login-field">发送给智能体的连接请求<textarea readOnly rows={5} value={prompt} onFocus={event => event.currentTarget.select()} /></label>
      <button type="button" className="btn btn-primary" onClick={() => {
        setCopied(false);
        navigator.clipboard?.writeText(prompt).then(() => setCopied(true)).catch(() => setError('复制未成功，请选中上方文字手动复制。'));
        if (!navigator.clipboard) setError('浏览器不支持复制，请选中上方文字手动复制。');
      }}>{copied ? '已复制，请发送给智能体' : '复制连接请求'}</button>{' '}
      <button type="button" className="btn" disabled={busy} onClick={() => void cancel()}>取消连接</button>
      <p role="status">等待本机确认 · 剩余 {seconds} 秒。请保持此页面打开。</p>
      <p className="login-desc">请求编号不是密码；另一个浏览器无法用它领取你的会话。</p>
    </>}
    {error ? <p role="alert" className="action-error">{error}</p> : null}
  </section>;
}
