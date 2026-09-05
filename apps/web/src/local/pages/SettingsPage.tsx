import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { localApi } from '../api';
import type { PlatformInfo } from '../types';
import { useLocalSession } from '../session';
import { adapterLabel, adapterTag, platformLabel } from '../format';

const MODES = ['block', 'warn', 'audit_only'] as const;

interface AuditEvent {
  at: string;
  event: string;
  actor_id?: string;
  target?: string;
  note?: string;
}

export default function SettingsPage() {
  const { status, error, actorId, setActorId, reload } = useLocalSession();
  const [mode, setMode] = useState(status?.enforcement_mode ?? 'block');
  const [msg, setMsg] = useState<string | null>(null);
  const [msgErr, setMsgErr] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [osTarget, setOsTarget] = useState('siq-as-live');
  const [osAllow, setOsAllow] = useState('');
  const [audit, setAudit] = useState<AuditEvent[]>([]);

  useEffect(() => {
    if (status?.enforcement_mode) setMode(status.enforcement_mode);
  }, [status?.enforcement_mode]);

  useEffect(() => {
    localApi
      .audit()
      .then((res) => setAudit(res.events ?? []))
      .catch(() => setAudit([]));
  }, [msg, status?.enforcement_mode]);

  const report = (text: string, isErr = false) => {
    setMsg(text);
    setMsgErr(isErr);
  };

  const saveMode = () => {
    setBusy('mode');
    setMsg(null);
    localApi
      .putConfig(mode)
      .then(() => {
        report(`enforcement_mode 已设为 ${mode}。已装适配器可能仍缓存旧模式，可重新安装以同步。`);
        reload();
      })
      .catch((err: unknown) => report(err instanceof Error ? err.message : '保存失败', true))
      .finally(() => setBusy(null));
  };

  const mutate = (platform: string, action: 'install' | 'uninstall') => {
    setBusy(`${action}:${platform}`);
    setMsg(null);
    const op = action === 'install' ? localApi.adapterInstall : localApi.adapterUninstall;
    op(platform)
      .then((res) => {
        report(`${platformLabel(res.platform)}：${res.action}${res.note ? ` — ${res.note}` : ''}`);
        reload();
      })
      .catch((err: unknown) => report(err instanceof Error ? err.message : '适配器操作失败', true))
      .finally(() => setBusy(null));
  };

  const probeOpenshell = () => {
    setBusy('openshell:probe');
    setMsg(null);
    localApi
      .openshellProbe()
      .then((res) => {
        const next = res.doctor?.human_next;
        report(
          res.ok
            ? `OpenShell L3 · ${res.schema_version ?? ''} — ${res.note ?? 'probe 成功'}`
            : `OpenShell 不可用（${res.tier}）：${next || res.note || 'probe 失败'}`,
          !res.ok,
        );
        reload();
      })
      .catch((err: unknown) => report(err instanceof Error ? err.message : 'probe 失败', true))
      .finally(() => setBusy(null));
  };

  const applyOpenshell = () => {
    const endpoints = osAllow
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!osTarget.trim() || endpoints.length === 0) {
      report('需要 sandbox 名和至少一个 host:port。', true);
      return;
    }
    setBusy('openshell:apply');
    setMsg(null);
    localApi
      .openshellApply({
        target: osTarget.trim(),
        network: endpoints.map((endpoint) => ({ endpoint, effect: 'allow' })),
        expect_allow: endpoints,
        expect_deny: ['192.0.2.1:1'],
      })
      .then((res) => {
        const rb = res.effective_readback;
        report(
          res.passed
            ? `读回 ${res.verify_level} · revision ${rb?.revision ?? '—'} · ${rb?.evidence_id ?? ''}`
            : `读回失败：${(res.failures ?? []).join('; ') || res.error || 'unknown'}`,
          !res.passed,
        );
        reload();
      })
      .catch((err: unknown) => report(err instanceof Error ? err.message : 'apply 失败', true))
      .finally(() => setBusy(null));
  };

  const adapterCols: TableColumn<PlatformInfo>[] = [
    {
      key: 'name',
      header: '平台',
      render: (p) => <span className="cell-nowrap">{platformLabel(p.name)}</span>,
    },
    { key: 'tier', header: '档位', render: (p) => <span className="cell-nowrap">{p.tier}</span> },
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
        if (p.name === 'trae') return <span className="muted-text">审计模式 · 无法阻断</span>;
        if (p.name === 'openshell') return <span className="muted-text">CLI 探针，无安装钩子</span>;
        const installed = p.adapter === 'installed';
        return (
          <span className="row-actions">
            <button
              type="button"
              className={`btn btn-sm${installed ? '' : ' btn-primary'}`}
              disabled={busy !== null}
              onClick={() => mutate(p.name, 'install')}
            >
              {busy === `install:${p.name}` ? '安装中…' : installed ? '重新安装' : '安装'}
            </button>
            {installed ? (
              <button
                type="button"
                className="btn btn-sm btn-danger"
                disabled={busy !== null}
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

  const auditCols: TableColumn<AuditEvent>[] = [
    { key: 'at', header: '时间', render: (ev) => <span className="mono">{ev.at}</span> },
    { key: 'event', header: '事件', render: (ev) => ev.event },
    { key: 'actor', header: '操作者', render: (ev) => ev.actor_id || '—' },
    { key: 'target', header: '对象', render: (ev) => <span className="mono">{ev.target || '—'}</span> },
    { key: 'note', header: '备注', render: (ev) => ev.note || '—' },
  ];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="settings"
        title="设置"
        description="本地模式没有租户登录。Token 只在内存；签名私钥不离开状态目录。"
        connection={status ? 'connected' : error ? 'disconnected' : 'loading'}
        connectionError={error}
      />
      {msg ? (
        msgErr ? (
          <p className="action-error" role="alert">
            {msg}
          </p>
        ) : (
          <div className="scan-result" role="status">
            <p>{msg}</p>
          </div>
        )
      ) : null}
      <div className="card">
        <h2>执行模式</h2>
        <p className="page-desc">
          block：决策 API 不可达即拒绝。warn / audit_only：放行并记录 advisory_action。
        </p>
        <div className="toolbar toolbar-end">
          <div className="field field-flush">
            <label htmlFor="mode">enforcement_mode</label>
            <select id="mode" value={mode} onChange={(e) => setMode(e.target.value)}>
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy !== null}
            onClick={saveMode}
          >
            {busy === 'mode' ? '保存中…' : '保存模式'}
          </button>
        </div>
      </div>
      <div className="card">
        <h2>人工身份</h2>
        <div className="field">
          <label htmlFor="actor-set">
            批准 / hold 签核使用的 actor_id（写入 sessionStorage，非 token）
          </label>
          <input id="actor-set" value={actorId} onChange={(e) => setActorId(e.target.value)} />
        </div>
      </div>
      <div className="card">
        <h2>平台适配器</h2>
        <p className="page-desc">安装会先备份再写钩子。Trae 没有工具钩子，操作为 skipped。</p>
        <SimpleTable
          columns={adapterCols}
          rows={status?.platforms ?? []}
          rowKey={(p) => p.name}
          emptyText="决策 API 不可达，暂时无法读取平台适配器状态。"
        />
      </div>
      <div className="card">
        <h2>OpenShell（L3）</h2>
        <p className="page-desc">
          接入已在运行、已验明的 OpenShell 网关（显式 SIQ_AS_* 优先，其次 ENV_SH，再 PATH）。probe
          必须验明网关是 OpenShell；连到 OpenClaw / Hermes 会失败。siq-agent-security 不会执行 gateway
          start。apply 只提交网络段；filesystem / process 保持当前读回，禁止
          create_generation。无 L3 时产品仍完整，控制台显示「仅工具层拦截」。
        </p>
        <div className="toolbar toolbar-end">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy !== null}
            onClick={probeOpenshell}
          >
            {busy === 'openshell:probe' ? '探测中…' : '探测网关'}
          </button>
        </div>
        <div className="field">
          <label htmlFor="os-target">sandbox / policy 名</label>
          <input id="os-target" value={osTarget} onChange={(e) => setOsTarget(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="os-allow">允许的 host:port（逗号或空格分隔）</label>
          <input
            id="os-allow"
            value={osAllow}
            onChange={(e) => setOsAllow(e.target.value)}
            placeholder="api.example.com:443"
          />
        </div>
        <button
          type="button"
          className="btn"
          disabled={busy !== null}
          onClick={applyOpenshell}
        >
          {busy === 'openshell:apply' ? '下发中…' : '下发网络段并读回'}
        </button>
      </div>
      <div className="card">
        <h2>脱敏导出</h2>
        <p className="page-desc">
          下载评委验收包：公钥、资产摘要、准入结论、回执哈希链校验、审计尾部。不含 token、私钥、Skill
          正文或工具参数。控制面同步请用 CLI <span className="mono">siq-agent-security sync</span>
          ，本控制台不会自动上传。
        </p>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy !== null}
          onClick={() => {
            setBusy('export');
            setMsg(null);
            localApi
              .downloadExport()
              .then(() => report('已下载 siq-agent-security-export.json'))
              .catch((err: unknown) => report(err instanceof Error ? err.message : '导出失败', true))
              .finally(() => setBusy(null));
          }}
        >
          {busy === 'export' ? '导出中…' : '下载导出包'}
        </button>
      </div>
      <div className="card">
        <h2>操作审计</h2>
        <p className="page-desc">
          来自 <span className="mono">audit.jsonl</span> 的最近记录。不含密钥、不含参数原文。
        </p>
        <SimpleTable
          columns={auditCols}
          rows={[...audit].reverse().slice(0, 40).map((ev, i) => ({ ...ev, idx: i }))}
          rowKey={(ev) => `${ev.idx}-${ev.at}-${ev.event}`}
          emptyText="暂无审计事件。安装适配器、批准签发、改模式都会写这里。"
        />
      </div>
      <div className="card">
        <h2>安全边界</h2>
        <ul className="page-desc">
          <li>本控制台无私钥；验签由 siq-agent-security verify / GET /v1/receipts 完成。</li>
          <li>Bearer token 来自 loopback 的 /ui-config.json，只留在内存，刷新会再取一次。</li>
          <li>OpenShell verify 最高只到 readback_verified；filesystem/process 永不标有效。</li>
        </ul>
      </div>
    </section>
  );
}
