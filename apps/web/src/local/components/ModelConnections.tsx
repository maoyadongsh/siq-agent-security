import { useEffect, useRef, useState } from 'react';
import { localApi } from '../api';
import { modelConfigLabels, modelResultLabels, type ModelConnections as Catalog, type ModelConnectionResult } from '../modelConnections';
import ModelInferenceTest from './ModelInferenceTest';

const roleLabel = { configured: '模型配置', primary: '默认配置', fallback: '备用配置' };
const credentialLabel = { present: '已找到已有凭据', missing: '未找到引用的凭据', none: '此配置未声明凭据', unsupported: '凭据来源需在原框架核对' };

export default function ModelConnections({ refreshKey = '' }: { refreshKey?: string }) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [selected, setSelected] = useState('');
  const [result, setResult] = useState<ModelConnectionResult>();
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const pending = useRef<AbortController | null>(null);
  const lastDiscovery = useRef(refreshKey);
  useEffect(() => {
    if (lastDiscovery.current === refreshKey || checking || testing || loading) return;
    const controller = new AbortController();
    localApi.modelConnections(controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      lastDiscovery.current = refreshKey;
      setCatalog(data);
      setSelected((old) => data.items.some((item) => item.id === old) ? old : data.items[0]?.id ?? '');
      setResult((old) => old && data.items.some((item) => item.id === old.id && item.fingerprint === old.fingerprint && item.can_check) ? old : undefined);
    }).catch(() => {
      if (controller.signal.aborted) return;
      lastDiscovery.current = refreshKey;
      setCatalog(undefined); setResult(undefined);
      setError('模型配置暂时无法读取，请重新发现。');
    });
    return () => controller.abort();
  }, [refreshKey, checking, testing, loading]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setResult(undefined); setCatalog(undefined);
    localApi.modelConnections(controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setCatalog(data); setSelected((old) => data.items.some((item) => item.id === old) ? old : data.items[0]?.id ?? '');
    }).catch(() => { if (!controller.signal.aborted) setError('模型配置暂时无法读取，请重新发现。'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    if (!result) return;
    setNow(Date.now()); const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [result]);
  const item = catalog?.items.find((row) => row.id === selected);
  const check = async () => {
    if (!item?.can_check || pending.current || loading) return;
    const controller = new AbortController(); pending.current = controller;
    setChecking(true); setError(''); setResult(undefined);
    try { const data = await localApi.checkModelConnection(item, controller.signal); if (!controller.signal.aborted) setResult(data); }
    catch { if (!controller.signal.aborted) setError('配置可能已变化，或本地检查未完成。请重新发现后再试。'); }
    finally { if (pending.current === controller) pending.current = null; if (!controller.signal.aborted) setChecking(false); }
  };
  return <section className="block-gap" aria-label="模型服务发现">
    <div className="toolbar"><h3>已有模型配置</h3><button className="btn btn-sm" type="button" disabled={loading || checking || testing} onClick={() => setAttempt((n) => n + 1)}>重新发现模型</button></div>
    <p className="page-desc">读取 Hermes 和 OpenClaw 的现有模型配置。“检查模型服务”只核对模型列表；“测试模型回答”会发送固定测试文本。两项操作都不切换模型、不发送业务数据。</p>
    {loading ? <p role="status">正在读取模型配置…</p> : null}
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    {catalog?.partial ? <p role="status">部分实例位置无法读取，当前列表可能不完整。</p> : null}
    {catalog && !catalog.items.length ? <p>尚未发现已有模型配置。请先在 Hermes 或 OpenClaw 中配置，再重新发现。</p> : null}
    {catalog?.items.length ? <div className="field"><label htmlFor="model-connection">选择模型配置</label>
      <select id="model-connection" value={selected} disabled={checking || testing} onChange={(e) => { setSelected(e.target.value); setResult(undefined); setError(''); }}>
        {catalog.items.map((row) => <option key={row.id} value={row.id}>{row.platform === 'hermes' ? 'Hermes' : 'OpenClaw'} · {row.instance_name} · {row.model || '模型未明确'} · {roleLabel[row.role]}</option>)}
      </select></div> : null}
    {item ? <>
      <p role="status">{modelConfigLabels[item.state]}</p>
      <p className="page-desc">{item.endpoint_display || '服务地址未明确'} · {credentialLabel[item.credential]}</p>
      <button type="button" className="btn" disabled={!item.can_check || loading || checking || testing} onClick={check}>{checking ? '正在检查模型服务…' : '检查模型服务'}</button>
    </> : null}
    {result ? <div role="status" className="notice"><strong>{now >= Date.parse(result.expires_at) ? '上次连接检查已过期，请重新检查' : modelResultLabels[result.status]}</strong>
      <p>仅核对模型列表，尚未验证实际推理。运行时可能存在角色覆盖、凭据继承或路由选择，请以原框架的实际运行记录为准。</p></div> : null}
    {catalog ? <p className="page-desc">配置读取于 {new Date(catalog.observed_at).toLocaleString('zh-CN', { hour12: false })}。备用配置不表示已切换；其他位置或不支持的配置不会自动补写。</p> : null}
    {item ? <ModelInferenceTest key={`${item.id}:${item.fingerprint}`} item={item} onBusy={setTesting} /> : null}
  </section>;
}
