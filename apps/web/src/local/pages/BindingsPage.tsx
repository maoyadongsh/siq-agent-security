import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { localApi } from '../api';
import type { PlatformInfo } from '../types';
import { useLocalSession } from '../session';
import {
  adapterLabel,
  adapterTag,
  hasOpenShellL3,
  platformLabel,
  platformTierText,
} from '../format';

type Probe = Awaited<ReturnType<typeof localApi.openshellProbe>>;

export default function BindingsPage() {
  const { status, error, reload } = useLocalSession();
  const [platforms, setPlatforms] = useState<PlatformInfo[]>(status?.platforms ?? []);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [probeErr, setProbeErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgErr, setMsgErr] = useState(false);
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
    setMsgErr(false);
    const op = action === 'install' ? localApi.adapterInstall : localApi.adapterUninstall;
    op(platform)
      .then((res) => {
        setMsg(`${platformLabel(res.platform)}：${res.action}${res.note ? ` — ${res.note}` : ''}`);
        load();
      })
      .catch((err: unknown) => {
        setMsg(err instanceof Error ? err.message : '适配器操作失败');
        setMsgErr(true);
      })
      .finally(() => setBusy(null));
  };

  const columns: TableColumn<PlatformInfo>[] = [
    {
      key: 'name',
      header: '平台',
      render: (p) => <span className="cell-nowrap">{platformLabel(p.name)}</span>,
    },
    {
      key: 'tier',
      header: '档位',
      render: (p) => <span className="cell-nowrap">{platformTierText(p, l3)}</span>,
    },
    {
      key: 'adapter',
      header: '适配器',
      render: (p) => <span className={adapterTag(p.adapter)}>{adapterLabel(p.adapter)}</span>,
    },
    { key: 'note', header: '说明', render: (p) => p.note || '—' },
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
      <PageHeader
        kicker="AGENTSHIELD"
        icon="bindings"
        title="运行时绑定"
        description="适配器钩子与可选 OpenShell 探针。可在此安装/卸载；网络段下发仍在设置页。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
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
      <div className="card">
        <h2>
          OpenShell{' '}
          {probe ? (
            <span className={probe.ok ? 'tag tag-ok' : 'tag tag-warn'}>
              {probe.ok ? 'L3 可用' : '不可用'}
            </span>
          ) : null}
        </h2>
        {probeErr ? (
          <div className="notice" role="status">
            <p className="notice-title">探针不可达</p>
            <p className="notice-detail">
              {probeErr}。无 L3 时顶栏写「仅工具层拦截」，产品仍完整：准入、签发、工具回执都不依赖
              OpenShell。
            </p>
          </div>
        ) : probe ? (
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
        <p className="page-desc block-gap">
          siq-agent-security 不执行 gateway start。无 L3 时顶栏写「仅工具层拦截」，产品仍完整。
        </p>
      </div>
    </section>
  );
}
