import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useConsoleContext } from '@/components/ConsoleContext';
import { onboardingApi, type OnboardingStatus } from '@/api/onboarding';
import { readDeviceCredentialStatus, revokeDeviceCredential, type DeviceCredentialStatus } from '@/api/deviceLifecycle';
import './device-lifecycle.css';

function DeviceAction({ environmentId, deviceId }: { environmentId: string; deviceId: string }) {
  const [params, setParams] = useSearchParams();
  const [value, setValue] = useState<DeviceCredentialStatus>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [retry, setRetry] = useState(0);
  const pending = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    const ticket = ++generation.current;
    setValue(undefined); setBusy(true); setError(''); setConfirmation('');
    void readDeviceCredentialStatus(environmentId, deviceId).then(result => {
      if (ticket === generation.current) setValue(result);
    }).catch(() => { if (ticket === generation.current) setError('无法核对设备凭据状态，不表示未吊销。请重新查询。'); })
      .finally(() => { if (ticket === generation.current) setBusy(false); });
    return () => { generation.current += 1; };
  }, [environmentId, deviceId, retry]);
  async function revoke() {
    if (pending.current || busy || value?.status !== 'active' || confirmation !== deviceId) return;
    pending.current = true; setBusy(true); setError('');
    const ticket = generation.current;
    const next = new URLSearchParams(params); next.set('device_revoke_pending', '1'); setParams(next, { replace: true });
    try {
      const result = await revokeDeviceCredential(environmentId, deviceId, confirmation);
      if (ticket === generation.current) setValue(result);
    } catch {
      if (ticket === generation.current) {
        setValue(undefined); setConfirmation('');
        setError('吊销结果未确认；请先查询原设备，不会自动重试。');
      }
    } finally { if (ticket === generation.current) { pending.current = false; setBusy(false); } }
  }
  return <section aria-label="设备吊销确认">
    <p>目标设备 ID：<strong>{deviceId}</strong></p>
    {params.has('device_revoke_pending') ? <p>此设备已有吊销尝试。查询只核对记录，不重放操作；未吊销记录也不能排除在途请求。</p> : null}
    {busy ? <p role="status">正在核对或提交，请稍候…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {value?.status === 'revoked' ? <p role="status">设备凭据已吊销。记录时间：{value.revoked_at}。不是业务权限撤销或离线进程已停止的证明。</p> : null}
    <button type="button" className="btn" disabled={busy} onClick={() => setRetry(n => n + 1)}>查询原设备状态</button>
    {value?.status === 'active' ? <>
      <p>当前记录尚未吊销，不表示设备在线或防御已生效。吊销后该设备后续接入请求将被拒绝；不能从此处重新启用。</p>
      <label className="field">输入设备 ID 确认吊销<input value={confirmation} disabled={busy} autoComplete="off" onChange={event => setConfirmation(event.target.value)} /></label>
      <button type="button" className="btn" disabled={busy || confirmation !== deviceId} onClick={() => void revoke()}>确认吊销设备凭据</button>
    </> : null}
  </section>;
}

function Manager({ environmentId }: { environmentId: string }) {
  const [params, setParams] = useSearchParams();
  const selected = params.get('credential_device') || '';
  const [open, setOpen] = useState(!!selected);
  const [progress, setProgress] = useState<OnboardingStatus>();
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setProgress(undefined); setError(false);
    void onboardingApi.status(environmentId).then(result => { if (active) setProgress(result); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [open, environmentId, retry]);
  return <section className="card device-lifecycle" aria-label="设备凭据管理">
    <h2>设备凭据管理</h2>
    <p>停止设备后续控制面接入；不删除资产或审计，不放宽现有策略，也不撤销智能体业务权限。</p>
    <button type="button" className="btn" disabled={open} aria-expanded={open} onClick={() => setOpen(true)}>管理设备凭据</button>
    {open ? <>
      {error ? <p role="alert">无法读取设备清单，不表示没有设备。<button type="button" className="btn" onClick={() => setRetry(n => n + 1)}>重试设备清单</button></p>
        : !progress ? <p role="status">正在读取设备清单…</p> : <>
          <p>已加载 {progress.devices.length} 台设备。{progress.devices_truncated ? '仅最近 100 台，不代表全部设备。' : ''}</p>
          <label className="field">选择管理设备<select value={selected} disabled={!!selected} onChange={event => {
            const next = new URLSearchParams(params); next.set('credential_device', event.target.value); setParams(next);
          }}><option value="">请选择设备</option>
            {selected && !progress.devices.some(device => device.id === selected) ? <option value={selected}>{selected}（不在当前清单，独立核对）</option> : null}
            {progress.devices.map(device => <option key={device.id} value={device.id}>{device.device_identity} · {device.id}</option>)}
          </select></label>
          {!progress.devices.length ? <p>本次返回的设备清单为空。</p> : null}
        </>}
      {selected ? <DeviceAction key={selected} environmentId={environmentId} deviceId={selected} /> : null}
      {selected ? <p>当前目标已固定；管理另一设备请从环境列表重新进入。本页刷新会只读核对原设备。</p> : null}
    </> : null}
  </section>;
}

export default function DeviceLifecyclePanel({ environmentId }: { environmentId: string }) {
  const { data, status } = useConsoleContext();
  if (status !== 'ready' || !data?.access.environments || !data.actions.enroll_devices) return null;
  return <Manager key={`${data.tenant.id}:${data.actor.type}:${data.actor.id}:${environmentId}`} environmentId={environmentId} />;
}
