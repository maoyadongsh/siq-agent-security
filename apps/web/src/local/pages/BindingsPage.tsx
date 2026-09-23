import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { localApi } from '../api';
import type { PlatformInfo } from '../types';
import { useLocalSession } from '../session';
import { useLoadGuard } from '../staleGuard';
import RuntimeCheckDialog from '../components/RuntimeCheckDialog';
import OpenShellEnvironment from '../components/OpenShellEnvironment';
import ModelConnections from '../components/ModelConnections';
import AdapterChangeDialog, { type AdapterChangeRequest } from '../components/AdapterChangeDialog';
import AdapterDiagnosisPanel from '../components/AdapterDiagnosisPanel';
import {
  adapterLabel,
  adapterTag,
  hasOpenShellL3,
  platformLabel,
  platformTierText,
} from '../format';

export default function BindingsPage() {
  const { status, error, reload } = useLocalSession();
  const [platforms, setPlatforms] = useState<PlatformInfo[]>(status?.platforms ?? []);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [discoveryKey, setDiscoveryKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const guard = useLoadGuard();
  const [msgErr, setMsgErr] = useState(false);

  const load = () => {
    setLoading(true);
    setLoadError(null);
    setDiscoveryKey((n) => n + 1);
    guard(() => localApi.adapterStatus())
      .then((data) => {
        if (data === undefined) return;
        setPlatforms(data.platforms ?? []);
        setLoading(false);
        reload();
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guard]);

  const l3 = hasOpenShellL3(platforms);

  const [runtimeCheckOpen, setRuntimeCheckOpen] = useState(false);
  const [adapterChange, setAdapterChange] = useState<AdapterChangeRequest | null>(null);
  const busy = adapterChange ? `${adapterChange.action}:${adapterChange.platform}` : null;
  const mutate = (platform: string, action: 'install' | 'uninstall') => {
    setMsg(null);
    setAdapterChange({ platform, action });
  };

  const columns: TableColumn<PlatformInfo>[] = [
    {
      key: 'name',
      header: '平台',
      render: (p) => <span className="cell-nowrap">{platformLabel(p.name)}</span>,
    },
    {
      key: 'tier',
      header: '接入状态',
      render: (p) => <span className="cell-nowrap">{platformTierText(p, l3)}</span>,
    },
    {
      key: 'adapter',
      header: '适配器',
      render: (p) => <span className={adapterTag(p.adapter)}>{adapterLabel(p.adapter)}</span>,
    },
    { key: 'note', header: '说明', render: (p) => <>{p.note || '—'}<AdapterDiagnosisPanel diagnosis={p.diagnosis} /></> },
    {
      key: 'act',
      header: '',
      render: (p) => {
        if (p.name === 'trae') {
          return <span className="muted-text">审计模式 · 无法阻断</span>;
        }
        if (p.name === 'openshell') {
          return <span className="muted-text">CLI 探针，无安装钩子</span>;
        }
        if (p.name === 'workbuddy' && p.diagnosis?.configuration_state === 'unsupported') {
          return p.adapter === 'installed'
            ? <button type="button" className="btn btn-sm btn-danger" disabled={!!busy} onClick={() => mutate(p.name, 'uninstall')}>卸载已有接入</button>
            : <span className="muted-text">当前范围不支持新接入</span>;
        }
        if (p.name === 'hermes') return <div className="toolbar"><button type="button" className="btn btn-sm" disabled={!!busy} onClick={() => mutate(p.name, 'install')}>管理实例</button><button type="button" className="btn btn-sm" disabled={!!busy} onClick={() => setRuntimeCheckOpen(true)}>运行自检</button></div>;
        const installed = p.adapter === 'installed';
        return (
          <span className="row-actions">
            <button
              type="button"
              className={`btn btn-sm${installed ? '' : ' btn-primary'}`}
              disabled={!!busy}
              onClick={() => mutate(p.name, 'install')}
            >
              {busy === `install:${p.name}` ? '安装中…' : installed ? '重新安装' : '安装'}
            </button>
            {installed ? (
              <button
                type="button"
                className="btn btn-sm btn-danger"
                disabled={!!busy}
                onClick={() => mutate(p.name, 'uninstall')}
              >
                {busy === `uninstall:${p.name}` ? '卸载中…' : '卸载'}
              </button>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <section>
      {runtimeCheckOpen ? <RuntimeCheckDialog onClose={() => setRuntimeCheckOpen(false)} /> : null}
      {adapterChange ? <AdapterChangeDialog request={adapterChange} onClose={() => setAdapterChange(null)} onApplied={(text) => { setAdapterChange(null); setMsg(text); setMsgErr(false); load(); }} /> : null}

      <PageHeader
        kicker="AGENTSHIELD"
        icon="bindings"
        title="运行时绑定"
        description="适配器钩子与可选 OpenShell 探针。可在此安装/卸载；网络段下发仍在设置页。"
        connection={loading ? 'loading' : error || loadError ? 'disconnected' : 'connected'}
        connectionError={loadError ?? error}
        actions={
          <button type="button" className="btn btn-sm" onClick={load}>
            <Icon name="refresh" size={14} /> 刷新
          </button>
        }
      />
      {msg ? (
        msgErr ? (
          <p className="action-error" role="alert">
            {msg}
          </p>
        ) : (
          <p className="sync-ok">{msg}</p>
        )
      ) : null}
      <div className="card">
        <h2>平台钩子</h2>
        <SimpleTable
          columns={columns}
          rows={platforms}
          rowKey={(p) => p.name}
          emptyText={
            loading
              ? '探测中…'
              : '未取得平台清单。确认决策 API 可达后点「刷新」。'
          }
        />
        <p className="page-desc block-gap">
          网络段下发仍在 <Link to="/settings">设置</Link>。安装会先备份再写钩子；安装/卸载会写{' '}
          <span className="mono">audit.jsonl</span>。
        </p>
      </div>
      <div className="card"><OpenShellEnvironment refreshKey={String(discoveryKey)} /></div>
      <div className="card"><ModelConnections /></div>
    </section>
  );
}
