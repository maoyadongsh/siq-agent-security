import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import EnvironmentSetup from '@/components/onboarding/EnvironmentSetup';
import InstallPlanSetup from '@/components/onboarding/InstallPlanSetup';
import EnterpriseConnectionPanel from '@/components/onboarding/EnterpriseConnectionPanel';
import DeviceLifecyclePanel from '@/components/device-lifecycle/DeviceLifecyclePanel';
import DiscoverySchedulePanel from '@/components/discovery-schedule-management/DiscoverySchedulePanel';
import { useApiList } from '@/hooks/useApiList';
import { ApiError } from '@/api/client';
import { onboardingApi, type OnboardingAccess } from '@/api/onboarding';
import type { Environment, EnvironmentType } from '@/api/types';
import './environments.css';

const empty: Environment[] = [];
const typeLabels: Record<EnvironmentType, string> = { host: '主机', container: '容器', k8s: 'Kubernetes', account: '云账号' };
const modeLabels = { discovery: '资产发现', observe: '观察', recommend: '建议', enforce: '执行策略' };
const columns: TableColumn<Environment>[] = [
  { key: 'name', header: '环境', render: e => <strong>{e.name}</strong> },
  { key: 'type', header: '类型', render: e => typeLabels[e.env_type] },
  { key: 'mode', header: '模式', render: e => modeLabels[e.mode] },
];
export default function EnvironmentsPage() {
  const environments = useApiList<Environment>('/environments', empty);
  const [params, setParams] = useSearchParams();
  const [access, setAccess] = useState<OnboardingAccess>();
  const [accessError, setAccessError] = useState(false);
  const [accessRetry, setAccessRetry] = useState(0);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [type, setType] = useState<EnvironmentType>('host');
  const [message, setMessage] = useState('');
  const pending = useRef(false);
  useEffect(() => {
    let active = true;
    onboardingApi.access().then(value => { if (active) { setAccess(value); setAccessError(false); } })
      .catch(() => { if (active) { setAccess(undefined); setAccessError(true); } });
    return () => { active = false; };
  }, [accessRetry]);
  const urlEnvironmentId = environments.status === 'connected' ? params.get('environment') : null;
  const selected = urlEnvironmentId ? environments.rows.find(row => row.id === urlEnvironmentId) : undefined;
  const selectedMissing = urlEnvironmentId !== null && !selected;
  const refreshing = environments.status === 'loading' && environments.rows.length > 0;
  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (pending.current || !name.trim()) return;
    pending.current = true; setCreating(true); setMessage('');
    try {
      const environment = await onboardingApi.create(name.trim(), type);
      if (!environment?.id) throw new Error('invalid environment response');
      setName(''); setParams({ environment: environment.id }); environments.refresh();
      setMessage('环境已创建。请确认安装计划范围，在目标设备完成安装后，本页会自动更新接入结果。');
    } catch (error) {
      setMessage(error instanceof ApiError && error.status === 409 ? '同名环境已存在，请刷新列表并选择该环境继续。'
        : error instanceof ApiError && error.status === 403 ? '当前账号没有创建环境的权限，请联系组织管理员。'
          : '未确认创建结果。请先刷新环境列表，核对是否已创建；输入已保留，不会自动重复提交。');
    } finally { pending.current = false; setCreating(false); }
  };
  return <section>
    <PageHeader icon="environments" title="环境与设备" description="选择环境、确认安装范围，在目标设备安装后查看自动更新的接入与发现结果。"
      connection={environments.status} connectionError={environments.error}
      actions={<button className="btn" onClick={() => { environments.reload(); setAccess(undefined); setAccessRetry(n => n + 1); }}>刷新环境列表</button>} />
    {environments.status === 'disconnected' ? <DisconnectedNotice error={environments.error} onRetry={environments.reload} /> : null}
    {accessError ? <p role="alert">无法读取接入权限，请刷新环境列表重试。</p> : null}
    {access?.can_create ? <form className="card" aria-label="创建环境" onSubmit={create}>
      <h2>添加环境</h2><p>填写名称和类型即可。新环境从资产发现开始，注册设备不会自动启用拦截。</p>
      <div className="form-row"><div className="field field-grow"><label htmlFor="environment-name">环境名称</label><input id="environment-name" value={name} maxLength={128} required onChange={e => setName(e.target.value)} placeholder="例如：研发 DGX Spark" /></div>
        <div className="field"><label htmlFor="environment-type">环境类型</label><select id="environment-type" value={type} onChange={e => setType(e.target.value as EnvironmentType)}>{Object.entries(typeLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></div></div>
      <button className="btn btn-primary" disabled={creating || environments.status !== 'connected' || !name.trim()}>{creating ? '正在创建…' : '创建环境并接入'}</button>
    </form> : access ? <p>当前账号可查看环境。创建环境需联系组织管理员或平台运维人员。</p> : null}
    {message ? <p role="status">{message}</p> : null}
    <div className={environments.rows.length ? 'environment-desktop-list' : undefined}>
      <SimpleTable columns={[...columns, {key:'setup', header:'操作', render: e => <button className="btn" disabled={environments.status !== 'connected'} onClick={() => setParams({environment:e.id})}>查看接入进度</button>}]} rows={environments.rows} rowKey={e => e.id} emptyText={environments.status === 'loading' ? '正在读取环境…' : environments.status === 'disconnected' ? '环境列表当前不可用。' : environments.listMeta?.truncated === false ? '尚无环境，请先创建。' : '未读取到环境记录，清单完整性无法确认。'} />
    </div>
    {environments.rows.length ? <ul className="environment-mobile-list" aria-label="环境列表">
      {environments.rows.map(environment => <li className="card" key={environment.id}>
        <strong>{environment.name}</strong><p>{typeLabels[environment.env_type]} · {modeLabels[environment.mode]}</p>
        <button className="btn" disabled={environments.status !== 'connected'} onClick={() => setParams({ environment: environment.id })}>查看接入进度</button>
      </li>)}
    </ul> : null}
    {environments.status === 'connected' || refreshing ? <div className="environment-list-footer">
      {refreshing ? <p className="environment-list-note" role="status">正在刷新环境列表…</p> : null}
      {environments.status === 'connected' && environments.coverageText ? <p className="environment-list-coverage" role="status">{environments.coverageText}</p> : null}
      {environments.hasMore ? <button type="button" className="btn" disabled={environments.status !== 'connected' || environments.loadingMore} onClick={() => { if (environments.status === 'connected') environments.loadMore(); }}>{environments.loadingMore ? '正在加载更多环境…' : '加载更多环境'}</button> : null}
      {environments.status === 'connected' && environments.error ? <p className="environment-list-error" role="alert">{environments.error}</p> : null}
    </div> : null}
    {selectedMissing ? <p className="environment-list-note" role="status">{environments.hasMore ? 'URL 指定的环境在当前已加载记录中尚未找到，可点击“加载更多环境”继续加载。' : 'URL 指定的环境在当前可见列表中未找到。'}</p> : null}
    {selected && access ? <div key={selected.id}>
      {access.can_enroll ? <InstallPlanSetup environment={selected.id} /> : null}
      <EnvironmentSetup environment={selected} access={access} />
      <EnterpriseConnectionPanel key={selected.id} environmentId={selected.id} />
      <DeviceLifecyclePanel environmentId={selected.id} />
      <DiscoverySchedulePanel environmentId={selected.id} />
    </div> : null}
  </section>;
}
