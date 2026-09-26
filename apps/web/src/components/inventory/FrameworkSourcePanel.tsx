import { useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import { getFrameworkSource, type FrameworkSourceView } from '@/api/frameworkSource';
import { useConsoleContext } from '@/components/ConsoleContext';

export function FrameworkSourceDetails({ value }: { value: FrameworkSourceView }) {
  if (value.status === 'no_recorded_source') return <p>尚无框架配置实例来源记录，不代表未安装框架或没有角色。</p>;
  if (!value.source) return <p>框架来源暂不可确认，不能按名称或目录猜测实例归属。</p>;
  const source = value.source;
  return <>
    <p>{source.framework === 'hermes' ? 'Hermes profile' : 'OpenClaw 配置实例'}的历史来源，不代表进程正在运行、技能已加载或权限已生效。</p>
    <dl className="kv-list">
      <dt>实例标识</dt><dd className="mono">{source.instance_key}</dd>
      <dt>采集设备</dt><dd className="mono">{source.device_id}</dd>
      <dt>环境</dt><dd className="mono">{source.environment_id}</dd>
      <dt>设备凭据</dt><dd>{source.device_revoked ? '已吊销，仅保留历史' : '未吊销，不代表当前在线'}</dd>
      <dt>观察时间</dt><dd><time dateTime={source.observed_at}>{source.observed_at}</time></dd>
    </dl>
    <p>仅同环境、同设备的实例标识可用于来源归组；技能安装关系仍未确认。</p>
    <details><summary>配置来源证据</summary><dl className="kv-list">
      <dt>配置摘要</dt><dd className="mono">{source.config_sha256}</dd>
      <dt>证据 ID</dt><dd className="mono">{source.evidence_id}</dd>
      <dt>观察 ID</dt><dd className="mono">{source.observation_id}</dd>
    </dl></details>
  </>;
}

function SourceRequest({ assetId }: { assetId: string }) {
  const [value, setValue] = useState<FrameworkSourceView>();
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    void getFrameworkSource(assetId).then(result => { if (active) setValue(result); })
      .catch(reason => { if (active) setError(reason instanceof ApiError && reason.status === 403
        ? '当前账号无权读取框架来源，请重新核对组织权限。'
        : '框架来源读取失败，不能据此判断没有框架。'); });
    return () => { active = false; };
  }, [assetId]);
  return error ? <p role="alert">{error}</p> : value ? <FrameworkSourceDetails value={value} /> : <p role="status">正在核对框架配置来源…</p>;
}

function SourcePanel({ assetId }: { assetId: string }) {
  const [attempt, setAttempt] = useState(0);
  return <section className="card" aria-label="框架配置实例来源" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
    <h2>框架配置实例来源</h2>
    <button type="button" className="btn" onClick={() => setAttempt(n => n + 1)}>重新核对框架来源</button>
    <SourceRequest key={attempt} assetId={assetId} />
  </section>;
}

export default function FrameworkSourcePanel({ assetId }: { assetId: string }) {
  const { data, status } = useConsoleContext();
  if (status !== 'ready' || !data?.access.agents || !data.access.environments) return null;
  return <SourcePanel key={JSON.stringify([data.tenant.id, data.actor.type, data.actor.id, assetId])} assetId={assetId} />;
}
