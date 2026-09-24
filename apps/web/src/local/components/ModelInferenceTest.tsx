import { useCallback, useEffect, useRef, useState } from 'react';
import { localApi } from '../api';
import type { ModelConnection } from '../modelConnections';
import { inferenceLabels, type ModelInferenceRecord } from '../modelInference';

export default function ModelInferenceTest({ item, onBusy }: { item: ModelConnection; onBusy: (busy: boolean) => void }) {
  const [record, setRecord] = useState<ModelInferenceRecord | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [now, setNow] = useState(Date.now());
  const pending = useRef<string>();
  const storageKey = `siq-model-test:${item.id}`;
  const request = useRef<AbortController>();
  const reading = useRef<AbortController>();
  const accept = useCallback((value: ModelInferenceRecord | null) => {
    setRecord(value); setLoaded(true);
    if (value && value.status !== 'running' && value.request_id === pending.current) {
      try { sessionStorage.removeItem(storageKey); } catch { /* The server record remains authoritative. */ }
      pending.current = undefined;
    }
  }, [storageKey]);
  const read = useCallback(async () => {
    reading.current?.abort(); const controller = new AbortController(); reading.current = controller;
    try { const value = await localApi.latestModelInference(item, controller.signal); if (!controller.signal.aborted) { accept(value); setError(''); } }
    catch { if (!controller.signal.aborted) { setLoaded(false); setError('暂时无法读取测试状态，请刷新状态；不会自动重新发送测试。'); } }
  }, [item, accept]);
  useEffect(() => {
    try { const saved = sessionStorage.getItem(storageKey); if (saved && /^mt-[0-9a-f]{32}$/.test(saved)) pending.current = saved; } catch { /* Creation will explain storage failure if necessary. */ }
    void read();
    return () => { reading.current?.abort(); request.current?.abort(); };
  }, [read, storageKey]);
  useEffect(() => {
    if (record?.status !== 'running') return;
    const timer = setInterval(() => { void read(); }, 1200); return () => clearInterval(timer);
  }, [record?.status, read]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const busy = submitting || record?.status === 'running';
  useEffect(() => { onBusy(busy); return () => onBusy(false); }, [busy, onBusy]);
  const start = async () => {
    if (!loaded || busy || request.current || !item.can_check) return;
    reading.current?.abort();
    let id = pending.current;
    if (!id) id = `mt-${crypto.randomUUID().replaceAll('-', '')}`;
    try { sessionStorage.setItem(storageKey, id); pending.current = id; }
    catch { setError('浏览器无法保存测试标识，请允许本地会话存储后重试。'); return; }
    const controller = new AbortController(); request.current = controller; setSubmitting(true); setError('');
    try { const value = await localApi.startModelInference(item, id, controller.signal); if (!controller.signal.aborted) accept(value); }
    catch { if (!controller.signal.aborted) { setError('测试提交尚未确认，可能已有测试进行中。请先刷新状态；再次提交会复用本次标识。'); setLoaded(false); } }
    finally { if (request.current === controller) request.current = undefined; if (!controller.signal.aborted) setSubmitting(false); }
  };
  const sameRequest = !pending.current || record?.request_id === pending.current;
  const current = record?.fingerprint === item.fingerprint;
  return <div className="block-gap" aria-label="模型回答测试">
    <p className="page-desc">回答测试会发送固定的公开测试文本，最多请求 512 个输出 token，可能消耗少量额度；不会发送业务数据或切换模型。</p>
    <div className="toolbar"><button className="btn" type="button" disabled={!loaded || busy || !item.can_check} onClick={start}>{busy ? '模型测试进行中…' : '测试模型回答'}</button>
      <button className="btn btn-sm" type="button" disabled={submitting} onClick={() => { void read(); }}>刷新测试状态</button></div>
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    {!loaded && !error ? <p role="status">正在读取上次测试状态…</p> : null}
    {record && loaded && (!current || sameRequest) ? <div className="notice" role="status"><strong>{!current ? '配置已变化，上次测试结果已失效' : record.status !== 'running' && now >= Date.parse(record.expires_at) ? '上次模型回答测试已过期' : inferenceLabels[record.status]}</strong>
      <p>开始于 {new Date(record.started_at).toLocaleString('zh-CN', { hour12: false })}。仅验证所选服务的固定文本回答，不代表智能体工具链或业务任务验证通过。</p></div> : null}
    <p className="page-desc">关闭页面后已提交的测试仍会完成；刷新只读取状态。本次服务会话内保留测试记录，重启本地服务后需重新测试。</p>
  </div>;
}
