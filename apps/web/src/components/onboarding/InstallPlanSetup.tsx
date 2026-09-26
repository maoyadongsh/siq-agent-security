import { useEffect, useRef, useState } from 'react';
import { ApiError } from '@/api/client';
import { installApi, type InstallOptions, type InstallPlan } from '@/api/installPlan';

/** Parent keys this component by environment: no plan may survive environment switching. */
export default function InstallPlanSetup({ environment }: { environment: string }) {
  const [options, setOptions] = useState<InstallOptions>();
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState('');
  const [arch, setArch] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [plan, setPlan] = useState<InstallPlan>();
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    installApi.options(environment).then(value => {
      if (active) { setOptions(value); setArch(value.releases[0].target_arch); }
    }).catch(e => {
      if (active) setError(e instanceof ApiError && e.status === 503 ? '自动接入发行配置尚不可用，请联系管理员配置可信安装包；仍可使用下方手动接入。'
        : e instanceof ApiError && e.status === 403 ? '生成安装计划需要环境管理和设备接入权限。' : '无法核验安装选项，请重试或使用手动接入。');
    });
    return () => { active = false; };
  }, [environment, retry]);
  useEffect(() => {
    if (!plan) return;
    const timer = setTimeout(() => setExpired(true), Math.max(0, Date.parse(plan.expires_at) - Date.now()));
    return () => clearTimeout(timer);
  }, [plan]);
  const release = options?.releases.find(r => r.target_arch === arch);
  const resetPlan = () => { setPlan(undefined); setConfirmed(false); setExpired(false); };
  const generate = async () => {
    if (pending.current || !options || !release || !confirmed || !selected.length) return;
    pending.current = true; setBusy(true); setError(''); setPlan(undefined); setExpired(false);
    try {
      const result = await installApi.create(options, release, selected);
      if (alive.current) setPlan(result);
    } catch {
      if (alive.current) setError('未取得可核验的安装计划，未注册设备或启动采集。请刷新安装选项后重试。');
    } finally { pending.current = false; if (alive.current) setBusy(false); }
  };
  const download = () => {
    if (!plan || Date.parse(plan.expires_at) <= Date.now()) { setExpired(true); return; }
    const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2) + '\n'], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${plan.plan_id}.json`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section className="card" aria-label="生成 Linux 安装计划">
    <h2>Linux 自动接入 · 安装计划</h2>
    <p>选择设备架构和采集范围。此步骤只生成计划，不注册设备、不上传文件、不授予智能体业务权限。</p>
    {error ? <p role="alert">{error}</p> : !options ? <p role="status">正在读取可信部署配置…</p> : null}
    <button className="btn" disabled={busy} onClick={() => { setOptions(undefined); setSelected([]); resetPlan(); setError(''); setRetry(n => n + 1); }}>刷新安装选项</button>
    {options && release ? <>
      <p>控制面：{options.control_plane_origin} · Linux 当前用户服务。发行签名需由目标设备安装器验证。</p>
      <fieldset disabled={busy}><legend>设备和采集范围</legend>
        <label htmlFor="install-arch">设备架构</label><select id="install-arch" value={arch} onChange={e => { setArch(e.target.value); setSelected([]); resetPlan(); }}>
          {options.releases.map(r => <option key={r.target_arch} value={r.target_arch}>{r.target_arch === 'arm64' ? 'ARM64（例如 DGX Spark）' : 'AMD64 / x86_64'} · {r.release_version}</option>)}
        </select>
        {release.connectors.map(c => <div key={c.id}>
          <label><input type="checkbox" checked={selected.includes(c.id)} onChange={e => { setSelected(previous => e.target.checked ? [...previous, c.id] : previous.filter(id => id !== c.id)); resetPlan(); }} />{c.id} · {c.version}</label>
          <p>目录：{c.scope.roots.join('、')}；文件：{c.scope.include.join('、')}</p>
        </div>)}
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已核对目标环境和采集范围，仅生成资产发现安装计划。</label>
      </fieldset>
      <button className="btn btn-primary" disabled={busy || !confirmed || !selected.length} onClick={() => void generate()}>{busy ? '正在生成…' : '生成安装计划'}</button>
    </> : null}
    {plan ? <div role="status"><p>计划已生成，尚未安装。{expired ? '计划已过期，请重新生成。' : `有效期至 ${new Date(plan.expires_at).toLocaleString()}。`}</p>
      <button className="btn" disabled={expired} onClick={download}>下载计划 JSON</button>
      <p>在目标 Linux 设备上使用可信安装器审阅并确认此计划。安装包、设备注册、心跳和发现上报仍需分别验证。</p>
    </div> : null}
  </section>;
}
