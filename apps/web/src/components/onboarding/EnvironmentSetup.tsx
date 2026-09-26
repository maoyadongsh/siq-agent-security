import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, describeApiError } from '@/api/client';
import { edgeCommands, eligibleScanDevices, onboardingApi, type OnboardingAccess, type OnboardingStatus } from '@/api/onboarding';
import type { Environment } from '@/api/types';
import OnboardingResults from './OnboardingResults';

const deviceLabels = { waiting: '已注册，等待心跳', online: '最近心跳正常', stale: '心跳已超时', revoked: '设备已停用' };
const scanLabels = { pending: '等待设备领取', uploaded: '已上传，等待完成回执', delivered: '扫描已完成', failed: '扫描失败', expired: '任务已过期' };
const utcDate = (value: string) => new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
const stamp = (value: string | null) => value ? utcDate(value).toLocaleString('zh-CN', { hour12: false }) : '尚未收到';

export default function EnvironmentSetup({ environment, access }: { environment: Environment; access: OnboardingAccess }) {
  const [progress, setProgress] = useState<OnboardingStatus>();
  const [readError, setReadError] = useState('');
  const [reading, setReading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const autoRefreshRef = useRef(true);
  const refreshRef = useRef<() => void>(() => {});
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const alive = useRef(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [code, setCode] = useState<{code: string; expires_at: string}>();
  const [address, setAddress] = useState('');
  const [os, setOS] = useState<'bash' | 'powershell'>('bash');
  const [confirmed, setConfirmed] = useState(false);
  const [connector, setConnector] = useState<'hermes' | 'openclaw'>('hermes');
  const [target, setTarget] = useState('');
  const commands = edgeCommands(address, os);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    let inFlight = false;
    const read = async () => {
      if (!active || inFlight) return;
      inFlight = true; setReading(true);
      try {
        const value = await onboardingApi.status(environment.id);
        if (active) { setProgress(value); setReadError(''); }
      } catch {
        if (active) { setProgress(undefined); setReadError('当前无法读取接入进度，请刷新重试。'); }
      } finally { inFlight = false; if (active) setReading(false); }
    };
    setProgress(undefined); setReadError('');
    refreshRef.current = () => { void read(); };
    void read();
    const timer = setInterval(() => {
      if (autoRefreshRef.current && document.visibilityState === 'visible') void read();
    }, 15000);
    return () => { active = false; clearInterval(timer); refreshRef.current = () => {}; };
  }, [environment.id]);
  useEffect(() => {
    if (!code) return;
    const timer = setTimeout(() => { setCode(undefined); setMessage('注册码已过期，可按需重新生成。'); }, Math.max(0, utcDate(code.expires_at).getTime() - Date.now()));
    return () => clearTimeout(timer);
  }, [code]);
  const refresh = () => refreshRef.current();
  const run = async (kind: 'enroll' | 'scan') => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setMessage('');
    try {
      if (kind === 'enroll') {
        const value = await onboardingApi.enroll(environment.id);
        if (alive.current) { setCode(value); setMessage('注册码已生成，仅本次显示。'); }
      } else {
        const current = await onboardingApi.status(environment.id);
        if (!alive.current) return;
        setProgress(current);
        if (!eligibleScanDevices(current, connector).some(device => device.device_identity === target)) {
          setError('所选设备当前不在线或不再支持此采集器，请刷新并重新选择；不会自动改派其他设备。');
          return;
        }
        const task = await onboardingApi.scan(environment.id, connector, target);
        if (alive.current) { setMessage(`发现任务已提交给设备 ${target}。运行中的企业后台服务会领取；手动模式请在该设备运行“领取发现任务”命令。任务：${task.task_id}`); refresh(); }
      }
    } catch (e) {
      if (alive.current) setError(e instanceof ApiError && e.status === 403 ? '当前账号没有此操作权限，请联系组织管理员。'
        : '操作未确认成功。请先刷新接入进度，核对已有任务或设备，避免重复提交。' + describeApiError(e, '服务暂不可用'));
    } finally { pending.current = false; if (alive.current) setBusy(false); }
  };
  const eligible = eligibleScanDevices(progress, connector);
  const selectedTarget = eligible.some(device => device.device_identity === target) ? target : '';
  const canScan = selectedTarget !== '';
  return <section className="card" aria-label="环境接入引导">
    <div className="toolbar"><h2>{environment.name} · 接入进度</h2><button className="btn" disabled={reading} onClick={refresh}>刷新接入进度</button></div>
    <label><input type="checkbox" checked={autoRefresh} onChange={event => { autoRefreshRef.current = event.target.checked; setAutoRefresh(event.target.checked); }} />每 15 秒自动更新进度（仅查询，不提交任务）</label>
    <p>注册、心跳和发现上报分别核对。接入仅用于资产采集，不表示智能体运行时权限已经生效。</p>
    {readError ? <p role="alert" className="action-error">{readError}</p> : !progress ? <p role="status">正在读取设备与发现记录…</p> : null}
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    {progress ? <OnboardingResults progress={progress} /> : null}
    {access.can_view_assets ? <p><Link to="/agents?view=candidates">查看组织资产清单</Link></p> : <p>查看资产需要资产读取权限，可联系组织管理员申请。</p>}
    <details><summary>高级：手动接入、补扫与详细记录</summary>
    <h3>1. 注册设备</h3>
    <p>先从可信部署渠道取得与目标系统匹配的 Edge 和 Connector 二进制。以下命令在目标设备的 Edge 所在目录执行，设备身份保存在当前用户目录；已有身份请直接启动心跳，不重复注册。</p>
    <div className="form-row">
      <div className="field field-grow"><label htmlFor="edge-address">设备可访问的控制面根地址</label><input id="edge-address" value={address} placeholder="https://security.example.com" onChange={event => { setAddress(event.target.value); setConfirmed(false); }} /><p className="field-hint">使用组织提供的地址；需能访问 /edge/v1，不填 /api/v1。远程设备不能使用本机回环地址。</p></div>
      <div className="field"><label htmlFor="edge-os">设备终端</label><select id="edge-os" value={os} onChange={event => setOS(event.target.value as typeof os)}><option value="bash">Linux / macOS（Bash）</option><option value="powershell">Windows（PowerShell）</option></select></div>
    </div>
    {address && !commands ? <p className="action-error">请输入无账号、密码、查询参数的 HTTPS 地址；本机测试可使用 HTTP 回环地址。</p> : null}
    <label className="permission-tool-choice"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />我已确认目标设备可访问此地址，并已准备好 Edge 与所选 Connector</label>
    {!access.can_enroll ? <p>生成注册码需要设备接入权限，请联系组织管理员或平台运维人员。</p> : <button className="btn btn-primary" disabled={busy || !commands || !confirmed || !!code} onClick={() => void run('enroll')}>{busy ? '正在提交…' : '生成一次性注册码'}</button>}
    {code ? <div className="block-gap">
      <label htmlFor="edge-enrollment">一次性注册码</label><input id="edge-enrollment" type="password" value={code.code} readOnly autoComplete="off" />
      <button className="btn" onClick={async () => { try { await navigator.clipboard.writeText(code.code); setMessage('注册码已复制，请在目标设备的提示中粘贴。'); } catch { setError('无法访问剪贴板，请选中注册码手动复制。'); } }}>复制注册码</button>
      <p>有效期至 {stamp(code.expires_at)}。只可注册一台设备；刷新页面后不再显示，已签发的码在到期或使用前仍有效。</p>
    </div> : null}
    {commands ? <><h4>注册命令</h4><pre className="onboarding-command">{commands.register}</pre><p>按提示粘贴注册码。命令不包含注册码；请勿把设备状态文件发给他人。</p>
      <h3>2. 保持设备在线</h3><pre className="onboarding-command">{commands.heartbeat}</pre><p>在设备终端持续运行，再刷新本页确认心跳。另开终端领取发现任务。</p></> : <h3>2. 核对设备心跳</h3>}
    {progress ? <>
      <p role="status">已注册 {progress.device_count} 台设备；当前展示 {progress.devices.length} 台。{progress.devices_truncated ? '仅显示最近 100 台，非完整设备清单。' : ''}</p>
      <ul>{progress.devices.map(device => <li key={device.id}><strong>{deviceLabels[device.status]}</strong> · 最近心跳：{stamp(device.last_seen_at)}<details><summary>设备标识与采集器</summary><p>{device.device_identity}</p><p>版本：{device.version}；声明采集器：{device.connectors.join('、') || '未声明'}</p></details></li>)}</ul>
      <p>心跳超过 {progress.heartbeat_stale_seconds} 秒视为超时；状态截至 {stamp(progress.evaluated_at)}。</p>
    </> : null}
    <h3>3. 发现智能体配置</h3>
    <div className="field"><label htmlFor="edge-connector">发现框架</label><select id="edge-connector" value={connector} disabled={busy} onChange={event => { setConnector(event.target.value as typeof connector); setTarget(''); }}><option value="hermes">Hermes</option><option value="openclaw">OpenClaw</option></select></div>
    <div className="field"><label htmlFor="edge-target">目标设备</label><select id="edge-target" value={selectedTarget} disabled={busy || eligible.length === 0} onChange={event => setTarget(event.target.value)}>
      <option value="">{eligible.length ? '请选择执行扫描的设备' : '暂无在线且支持此采集器的设备'}</option>
      {eligible.map(device => <option key={device.id} value={device.device_identity}>{device.device_identity} · {device.version}</option>)}
    </select></div>
    <p>本次范围：{connector === 'hermes' ? '~/.hermes/profiles/* 下的 config.yaml、SOUL.md' : '~/.openclaw 下的 openclaw.json'}。仅由所选设备领取，不自动改派；范围必须符合该设备安装时确认的范围。</p>
    {access.can_scan ? <button className="btn btn-primary" disabled={busy || !canScan} onClick={() => void run('scan')}>提交发现任务</button> : <p>提交发现任务需要环境管理权限。</p>}
    {!canScan ? <p>请选择在线且支持此采集器的设备；缺少设备时请恢复后台服务并刷新进度。能力声明不等于已完成盘点。</p> : null}
    {commands ? <><h4>在设备上领取发现任务</h4><pre className="onboarding-command">{commands.tasks}</pre><p>确保所选 Connector 位于 PATH，或已设置 SIQ_CONNECTOR_BIN_DIR。该命令执行当前环境队列中已签名的待处理任务。</p></> : null}
    {progress ? <>
      <p>本环境已保存 {progress.evidence_count} 条发现证据；最近上报：{stamp(progress.last_evidence_at)}。</p>
      {progress.scans.length ? <ul>{progress.scans.map(scan => <li key={scan.id}><strong>{scanLabels[scan.status]}</strong> · {scan.connector} · {stamp(scan.created_at)}
        {scan.candidate_count !== null ? <p>本次回执上报对象 {scan.candidate_count} 项、证据 {scan.evidence_count ?? '未记录'} 条。{scan.candidate_count === 0 ? '未发现对象，请核对设备上的框架配置与扫描范围。' : '请在资产清单中查看候选，发现不等于已纳管。'}</p> : null}
        <details><summary>任务标识</summary><p>{scan.id}</p><p>领取设备：{scan.device_identity || '尚未领取'}</p></details></li>)}</ul> : <p>尚无发现任务。</p>}
      {progress.scans_truncated ? <p>仅展示最近 20 个发现任务。</p> : null}
    </> : null}
    </details>
  </section>;
}
