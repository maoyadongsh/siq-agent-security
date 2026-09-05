import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import { localApi } from '../api';
import type { PlatformInfo } from '../types';
import { useLocalSession } from '../session';
import { hasOpenShellL3, platformLabel, platformTierText } from '../format';

type Probe = Awaited<ReturnType<typeof localApi.openshellProbe>>;

export default function BindingsPage() {
  const { status, error, reload } = useLocalSession();
  const [platforms, setPlatforms] = useState<PlatformInfo[]>(status?.platforms ?? []);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [probeErr, setProbeErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([localApi.adapterStatus(), localApi.openshellProbe().catch((err: unknown) => err)])
      .then(([st, os]) => {
        setPlatforms(st.platforms ?? []);
        if (os instanceof Error) {
          setProbe(null);
          setProbeErr(os.message);
        } else {
          setProbe(os as Probe);
          setProbeErr(null);
        }
        setLoading(false);
        reload();
      })
      .catch((err: unknown) => {
        setProbeErr(err instanceof Error ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const l3 = hasOpenShellL3(platforms);

  const mutate = (platform: string, action: 'install' | 'uninstall') => {
    setBusy(`${action}:${platform}`);
    setMsg(null);
    const op = action === 'install' ? localApi.adapterInstall : localApi.adapterUninstall;
    op(platform)
      .then((res) => {
        setMsg(`${res.platform}: ${res.action}${res.note ? ` — ${res.note}` : ''}`);
        load();
      })
      .catch((err: unknown) => setMsg(err instanceof Error ? err.message : '适配器操作失败'))
      .finally(() => setBusy(null));
  };

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="bindings"
        title="运行时绑定"
        description="适配器钩子与可选 OpenShell 探针。可在此安装/卸载；网络段下发仍在设置页。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
      />
      {msg ? <p className="page-desc">{msg}</p> : null}
      <div className="card">
        <h2>平台钩子</h2>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>平台</th>
                <th>档位</th>
                <th>适配器</th>
                <th>说明</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {platforms.map((p) => (
                <tr key={p.name}>
                  <td>{platformLabel(p.name)}</td>
                  <td>{platformTierText(p, l3)}</td>
                  <td>{p.adapter}</td>
                  <td>{p.note}</td>
                  <td>
                    {p.name === 'trae' ? (
                      <span className="page-desc">审计 only</span>
                    ) : p.name === 'openshell' ? (
                      <span className="page-desc">CLI 探针，无安装钩子</span>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={!!busy}
                          onClick={() => mutate(p.name, 'install')}
                        >
                          安装
                        </button>{' '}
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={!!busy}
                          onClick={() => mutate(p.name, 'uninstall')}
                        >
                          卸载
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="page-desc">
          网络段下发仍在 <Link to="/settings">设置</Link>。安装/卸载会写 <span className="mono">audit.jsonl</span>。
        </p>
      </div>
      <div className="card">
        <h2>OpenShell</h2>
        {probeErr ? <p className="page-desc">{probeErr}</p> : null}
        {probe ? (
          <dl className="kv-list">
            <dt>probe</dt>
            <dd>{probe.ok ? '成功' : '失败'}</dd>
            <dt>档位</dt>
            <dd>{probe.tier}</dd>
            <dt>说明</dt>
            <dd>{probe.note || '—'}</dd>
            <dt>schema</dt>
            <dd>{probe.schema_version || '—'}</dd>
            <dt>下一步</dt>
            <dd>{probe.doctor?.human_next || '—'}</dd>
          </dl>
        ) : (
          <p className="page-desc">尚未取得探针结果。</p>
        )}
        <p className="page-desc" style={{ marginTop: 12 }}>
          AgentShield 不执行 gateway start。无 L3 时顶栏写「仅工具层拦截」，产品仍完整。
        </p>
      </div>
    </section>
  );
}
