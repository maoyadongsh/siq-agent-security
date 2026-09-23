import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { localApi } from '../api';
import { configurationLabel, platformLabel } from '../format';
import type { AdapterInstance } from '../types';
import AdapterChangeDialog, { type AdapterChangeRequest } from './AdapterChangeDialog';
import RuntimeCheckDialog from './RuntimeCheckDialog';
import OpenShellEnvironment from './OpenShellEnvironment';
import ModelConnections from './ModelConnections';

const platforms = ['hermes', 'openclaw'] as const;

export default function EnvironmentConnections({ refreshKey }: { refreshKey: string }) {
  const [instances, setInstances] = useState<AdapterInstance[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [change, setChange] = useState<AdapterChangeRequest | null>(null);
  const [check, setCheck] = useState<string>();
  const [message, setMessage] = useState('');
  const [installedInstance, setInstalledInstance] = useState<string>();
  const verifiedInstall = !loading && instances.find((instance) => instance.platform === 'hermes'
    && instance.instance_id === installedInstance && instance.diagnosis.configuration_state === 'ready');
  useEffect(() => {
    let active = true;
    setLoading(true);
    setInstances([]);
    setFailed([]);
    void Promise.allSettled(platforms.map((platform) => localApi.adapterInstances(platform))).then((results) => {
      if (!active) return;
      setInstances(results.flatMap((result) => result.status === 'fulfilled'
        ? result.value.instances.filter((instance) => instance.detected) : []));
      setFailed(results.flatMap((result, index) => result.status === 'rejected'
        || result.value.issues.length > 0 ? [platformLabel(platforms[index])] : []));
      setLoading(false);
    });
    return () => { active = false; };
  }, [refreshKey, attempt]);

  return <div className="block-gap">
    <h3>选择要接入的智能体</h3>
    <p className="page-desc">已自动读取现有实例。选择后核对权限并应用配置，无需复制路径或手工编辑配置文件。</p>
    {loading ? <p role="status">正在识别 Hermes 和 OpenClaw 实例…</p> : null}
    {!loading && instances.length === 0 ? <p role="status">暂未发现可接入实例。安装 Hermes 或 OpenClaw 后点“重新发现”；自定义位置可在高级选项中查看。</p> : null}
    <div className="environment-connections">{instances.map((instance) => <article className="environment-connection" key={`${instance.platform}:${instance.instance_id}`}>
      <div><strong>{platformLabel(instance.platform)} · {instance.name}</strong>
        <p className="page-desc">{configurationLabel(instance.diagnosis.configuration_state)}{instance.active ? ' · 当前实例' : ''}</p>
        <details><summary>{instance.source === 'registered_project' ? '查看项目位置' : '查看位置'}</summary><code>{instance.config_dir}</code></details>
      </div>
      <div className="toolbar">
        <button type="button" className="btn btn-primary" onClick={() => {
          setMessage(''); setInstalledInstance(undefined); setChange({ platform: instance.platform, action: 'install', instanceId: instance.instance_id });
        }}>{instance.diagnosis.configuration_state === 'ready' ? '管理此实例' : '接入此实例'}</button>
        {instance.platform === 'hermes' && instance.diagnosis.configuration_state === 'ready'
          ? <button type="button" className="btn" onClick={() => setCheck(instance.instance_id)}>验证连接</button> : null}
      </div>
    </article>)}</div>
    {failed.length ? <p role="status">{failed.join('、')} 的部分位置暂时无法识别。<button type="button" className="btn btn-sm" disabled={loading} onClick={() => setAttempt((value) => value + 1)}>重试识别</button></p> : null}
    {message ? <p role="status">{message}</p> : null}
    {verifiedInstall ? <div className="toolbar">
      <span>下一步：验证 {verifiedInstall.name} 的正常调用和越权拦截。</span>
      <button type="button" className="btn btn-primary" onClick={() => setCheck(verifiedInstall.instance_id)}>验证刚接入的实例</button>
    </div> : null}
    <p className="page-desc">接入后可验证实际工具调用。<Link to="/bindings">查看 OpenShell 与运行环境</Link> · <Link to="/agents">查看全部智能体与 Skill</Link></p>
    <OpenShellEnvironment />
    <ModelConnections refreshKey={refreshKey} />
    {change ? <AdapterChangeDialog request={change} onClose={() => setChange(null)} onApplied={(text, applied) => {
      setInstalledInstance(applied?.platform === 'hermes' && applied.action === 'install' ? applied.instanceId : undefined);
      setChange(null); setMessage(text); setAttempt((value) => value + 1);
    }} /> : null}
    {check ? <RuntimeCheckDialog instanceId={check} onClose={() => setCheck(undefined)} /> : null}
  </div>;
}
