import { useCallback, useEffect, useState } from 'react';
import Modal from '@/components/Modal';
import { localApi } from '../api';
import { configurationLabel, platformLabel } from '../format';
import AdapterDiagnosisPanel from './AdapterDiagnosisPanel';
import type { AdapterPlan, AdapterInstances } from '../types';
import { useInstancePermissions } from './useInstancePermissions';
import { useLocalSession } from '../session';

export interface AdapterChangeRequest { platform: string; action: 'install' | 'uninstall'; instanceId?: string; grantId?: string }
interface Props { request: AdapterChangeRequest; onClose: () => void; onApplied: (message: string) => void }
const actionLabel = { create: '新增', replace: '修改', remove: '移除' };

export default function AdapterChangeDialog({ request, onClose, onApplied }: Props) {
  const { actorId } = useLocalSession();
  const [connectionMode, setConnectionMode] = useState<'permissions' | 'connection'>('permissions');
  const [action, setAction] = useState(request.action);
  const [catalog, setCatalog] = useState<AdapterInstances | null>(null);
  const [instanceId, setInstanceId] = useState('');
  const [nativeEnable, setNativeEnable] = useState(false);
  const selected = catalog?.instances.find((item) => item.instance_id === instanceId);
  const [plan, setPlan] = useState<AdapterPlan | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const permissions = useInstancePermissions(request.platform === 'hermes' && action === 'install' && connectionMode === 'permissions' ? instanceId : '', busy, request.grantId);
  const working = busy || permissions.busy;
  const close = useCallback(() => { if (!working) onClose(); }, [working, onClose]);
  useEffect(() => {
    if (request.platform !== 'hermes') return;
    let active = true;
    setLoading(true); setError('');
    localApi.adapterInstances(request.platform).then((result) => {
      if (!active) return;
      setCatalog(result);
      const target = request.instanceId ? result.instances.find((item) => item.instance_id === request.instanceId) : result.instances.find((item) => item.active) ?? result.instances[0];
      setInstanceId(target?.instance_id ?? '');
      if (!target) { setError('未找到此安装对应的实例，请重新发现后重试。'); setLoading(false); }
      setNativeEnable(result.native_available);
      if (result.instances.length === 0) { setError('未找到可接入实例，请检查目录并重新发现。'); setLoading(false); }
    }).catch((err: unknown) => { if (active) { setError(err instanceof Error ? err.message : '无法读取实例'); setLoading(false); } });
    return () => { active = false; };
  }, [request.platform, request.instanceId, catalogAttempt]);
  useEffect(() => {
    if (request.platform === 'hermes' && (!instanceId || action === 'install' && connectionMode === 'permissions' && !permissions.identityId)) {
      setPlan(null); setLoading(false); return;
    }
    let active = true;
    setLoading(true); setError(''); setPlan(null);
    localApi.adapterPreview(request.platform, action, instanceId || undefined, action === 'install' && nativeEnable, action === 'install' && connectionMode === 'permissions' ? permissions.identityId : undefined)
      .then((view) => { if (active) setPlan(view); })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : '预览失败'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [request.platform, action, instanceId, nativeEnable, attempt, connectionMode, permissions.identityId]);

  const apply = async () => {
    if (!plan || working || loading || plan.instance_id !== (instanceId || undefined) || plan.action !== action) return;
    if (action === 'install' && request.platform === 'hermes' && connectionMode === 'permissions' && plan.runtime_identity_id !== permissions.identityId) return;
    setBusy(true); setError('');
    try {
      await localApi.adapterApply(plan, actorId);
      onApplied(action === 'install'
        ? `${platformLabel(request.platform)}${selected ? ` / ${selected.name}` : ''}：配置已应用，请查看诊断并验证实际调用。`
        : `${platformLabel(request.platform)}${selected ? ` / ${selected.name}` : ''}：接入配置已移除，其他平台设置已保留。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请检查状态后重试');
      setPlan(null);
    } finally { setBusy(false); }
  };
  const recover = async () => {
    if (request.platform === 'hermes' && !instanceId) return;
    setBusy(true); setError('');
    try {
      const result = await localApi.adapterRecover(request.platform, instanceId || undefined);
      onApplied(result.action === 'no_recovery_needed'
        ? '没有待恢复的中断操作。请检查平台配置后重新预览。'
        : '中断操作已恢复。请重新查看诊断，再决定是否接入。');
    } catch (err) { setError(err instanceof Error ? err.message : '恢复未完成，现有修改已保留'); }
    finally { setBusy(false); }
  };
  return <><Modal open={!permissions.editing} className="grant-resource-modal" onClose={close} title={`${platformLabel(request.platform)} · ${action === 'install' ? '接入' : '卸载'}预览`}
    description="确认后才会应用以下变更，并保存本机恢复记录。预览有效期为 5 分钟；配置变化时需要重新预览。">
    <div className="modal-body adapter-change-body" aria-busy={loading || working}>
      {catalog ? <>
        <div className="field field-flush">
          <label htmlFor="adapter-instance">Hermes 实例 / profile</label>
          <select id="adapter-instance" disabled={working || !!request.instanceId} value={instanceId} onChange={(event) => { setPlan(null); setLoading(true); setInstanceId(event.target.value); }}>
            {catalog.instances.map((item) => <option key={item.instance_id} value={item.instance_id}>{item.name} · {item.config_dir}</option>)}
          </select>
        </div>
        <div className="field field-flush">
          <label htmlFor="adapter-action">操作</label>
          <select id="adapter-action" disabled={working || !!request.grantId} value={action} onChange={(event) => { setPlan(null); setLoading(true); setAction(event.target.value as 'install' | 'uninstall'); }}>
            <option value="install">安装或修复接入</option><option value="uninstall">卸载此实例接入</option>
          </select>
        </div>
        {selected ? <>
          <p>本次检查：<strong>{configurationLabel(selected.diagnosis.configuration_state)}</strong></p>
          <AdapterDiagnosisPanel diagnosis={selected.diagnosis} />
        </> : null}
        {action === 'install' ? <>
          <div className="field"><label htmlFor="instance-connection-mode">接入方式</label>
            <select id="instance-connection-mode" value={connectionMode} disabled={working || !!request.grantId} onChange={(event) => { setPlan(null); setConnectionMode(event.target.value as 'permissions' | 'connection'); }}>
              <option value="permissions">配置实例权限并接入</option><option value="connection">仅安装连接组件</option>
            </select>
          </div>
          {connectionMode === 'permissions' ? permissions.panel : <p>此步骤仅配置平台钩子，不建立新的日常会话授权；已有实例身份会保留。</p>}
        </> : null}
        {action === 'install' ? <label className="adapter-native-option">
          <input type="checkbox" checked={nativeEnable} disabled={working || !catalog.native_available} onChange={(event) => { setPlan(null); setLoading(true); setNativeEnable(event.target.checked); }} />
          由 Hermes 同步启用本实例插件
        </label> : null}
        {!catalog.native_available ? <p>未找到 Hermes CLI，可先安装接入文件，再在原平台启用插件。</p> : null}
        {catalog.issues.length > 0 ? <p role="status">部分实例目录未能读取，请检查扫描结果与目录权限。</p> : null}
      </> : null}
      {loading ? <p role="status">正在检查配置并准备变更清单…</p> : null}
      {error ? <p className="action-error" role="alert">{error}</p> : null}
      {plan ? <>
        <p>涉及 {plan.changes.length} 个文件。{plan.changes.length === 0 ? '当前文件无需修改。' : ''}</p>
        <ul className="adapter-change-list">{plan.changes.map((change) => <li key={change.path}>
          <strong>{actionLabel[change.action]}</strong> <code>{change.path}</code>
          <p>{change.purpose}</p>
          <details><summary tabIndex={0}>校验摘要</summary><p>变更前：<code>{change.before_sha256 || '文件不存在'}</code></p><p>变更后：<code>{change.after_sha256 || '文件移除'}</code></p></details>
        </li>)}</ul>
        <ul>{plan.next_steps.map((step) => <li key={step}>{step}</li>)}</ul>
      </> : null}
      {error ? <>
        <button type="button" className="btn" disabled={working || loading} onClick={() => {
          if (request.platform === 'hermes' && !instanceId) setCatalogAttempt((n) => n + 1);
          else setAttempt((n) => n + 1);
        }}>重新预览</button>
        <p>如果上次操作中断，可尝试恢复；遇到其他程序改动的文件会停止并保留，恢复不会继续安装。</p>
        <button type="button" className="btn" disabled={working || (request.platform === 'hermes' && !instanceId)} onClick={recover}>恢复中断操作</button>
      </> : null}
    </div>
    <div className="modal-actions">
      <button type="button" className="btn" disabled={working} onClick={close}>取消</button>
      <button type="button" className="btn btn-primary" disabled={!plan || loading || working} onClick={apply}>{busy ? '处理中…' : '确认应用'}</button>
    </div>
  </Modal>{permissions.editor}</>;
}
