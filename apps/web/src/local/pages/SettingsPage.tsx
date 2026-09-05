import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import { platformLabel } from '../format';

const MODES = ['block', 'warn', 'audit_only'] as const;

export default function SettingsPage() {
  const { status, error, actorId, setActorId, reload } = useLocalSession();
  const [mode, setMode] = useState(status?.enforcement_mode ?? 'block');
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [osTarget, setOsTarget] = useState('siq-as-live');
  const [osAllow, setOsAllow] = useState('');
  const [audit, setAudit] = useState<{ at: string; event: string; actor_id?: string; target?: string; note?: string }[]>([]);

  useEffect(() => {
    if (status?.enforcement_mode) setMode(status.enforcement_mode);
  }, [status?.enforcement_mode]);

  useEffect(() => {
    localApi
      .audit()
      .then((res) => setAudit(res.events ?? []))
      .catch(() => setAudit([]));
  }, [msg, status?.enforcement_mode]);

  const saveMode = () => {
    setMsg(null);
    localApi
      .putConfig(mode)
      .then(() => {
        setMsg(`enforcement_mode 已设为 ${mode}。已装适配器可能仍缓存旧模式，可重新安装以同步。`);
        reload();
      })
      .catch((err: unknown) => setMsg(err instanceof Error ? err.message : '保存失败'));
  };

  const mutate = (platform: string, action: 'install' | 'uninstall') => {
    setBusy(`${action}:${platform}`);
    setMsg(null);
    const op = action === 'install' ? localApi.adapterInstall : localApi.adapterUninstall;
    op(platform)
      .then((res) => {
        setMsg(`${res.platform}: ${res.action}${res.note ? ` — ${res.note}` : ''}`);
        reload();
      })
      .catch((err: unknown) => setMsg(err instanceof Error ? err.message : '适配器操作失败'))
      .finally(() => setBusy(null));
  };

  const probeOpenshell = () => {
    setBusy('openshell:probe');
    setMsg(null);
    localApi
      .openshellProbe()
      .then((res) => {
        const next = res.doctor?.human_next;
        setMsg(
          res.ok
            ? `OpenShell L3 · ${res.schema_version ?? ''} — ${res.note ?? 'probe 成功'}`
            : `OpenShell 不可用（${res.tier}）：${next || res.note || 'probe 失败'}`,
        );
        reload();
      })
      .catch((err: unknown) => setMsg(err instanceof Error ? err.message : 'probe 失败'))
      .finally(() => setBusy(null));
  };

  const applyOpenshell = () => {
    const endpoints = osAllow
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!osTarget.trim() || endpoints.length === 0) {
      setMsg('需要 sandbox 名和至少一个 host:port。');
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
        setMsg(
          res.passed
            ? `读回 ${res.verify_level} · revision ${rb?.revision ?? '—'} · ${rb?.evidence_id ?? ''}`
            : `读回失败：${(res.failures ?? []).join('; ') || res.error || 'unknown'}`,
        );
        reload();
      })
      .catch((err: unknown) => setMsg(err instanceof Error ? err.message : 'apply 失败'))
      .finally(() => setBusy(null));
  };

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
      <div className="card">
        <h2>执行模式</h2>
        <p className="page-desc">
          block：决策 API 不可达即拒绝。warn / audit_only：放行并记录 advisory_action。
        </p>
        <div className="field">
          <label htmlFor="mode">enforcement_mode</label>
          <select id="mode" value={mode} onChange={(e) => setMode(e.target.value)}>
            {MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <button type="button" className="btn btn-primary" onClick={saveMode}>
          保存模式
        </button>
      </div>
      <div className="card">
        <h2>人工身份</h2>
        <div className="field">
          <label htmlFor="actor-set">批准 / hold 签核使用的 actor_id（写入 sessionStorage，非 token）</label>
          <input id="actor-set" value={actorId} onChange={(e) => setActorId(e.target.value)} />
        </div>
      </div>
      <div className="card">
        <h2>平台适配器</h2>
        <p className="page-desc">安装会先备份再写钩子。Trae 没有工具钩子，操作为 skipped。</p>
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
              {(status?.platforms ?? []).map((p) => (
                <tr key={p.name}>
                  <td>{platformLabel(p.name)}</td>
                  <td>{p.tier}</td>
                  <td>{p.adapter}</td>
                  <td>{p.note}</td>
                  <td>
                    {p.name === 'trae' ? (
                      <span className="page-desc">审计 only</span>
                    ) : p.name === 'openshell' ? (
                      <span className="page-desc">CLI 探针，无安装钩子</span>
                    ) : (
                      <span className="toolbar" style={{ marginBottom: 0 }}>
                        <button
                          type="button"
                          className="btn btn-sm btn-primary"
                          disabled={busy !== null}
                          onClick={() => mutate(p.name, 'install')}
                        >
                          安装
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={busy !== null}
                          onClick={() => mutate(p.name, 'uninstall')}
                        >
                          卸载
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h2>OpenShell（L3）</h2>
        <p className="page-desc">
          接入已在运行、已验明的 OpenShell 网关（显式 SIQ_AS_* 优先，其次 ENV_SH，再 PATH）。probe
          必须验明网关是 OpenShell；连到 OpenClaw / Hermes 会失败。agentshield 不会执行 gateway
          start。apply 只提交网络段；filesystem / process 保持当前读回，禁止 create_generation。无
          L3 时产品仍完整，控制台显示「仅工具层拦截」。
        </p>
        <div className="toolbar">
          <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={probeOpenshell}>
            探测网关
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
        <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={applyOpenshell}>
          下发网络段并读回
        </button>
      </div>
      <div className="card">
        <h2>脱敏导出</h2>
        <p className="page-desc">
          下载评委验收包：公钥、资产摘要、准入结论、回执哈希链校验、审计尾部。不含 token、私钥、Skill
          正文或工具参数。控制面同步请用 CLI <span className="mono">agentshield sync</span>
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
              .then(() => setMsg('已下载 agentshield-export.json'))
              .catch((err: unknown) => setMsg(err instanceof Error ? err.message : '导出失败'))
              .finally(() => setBusy(null));
          }}
        >
          下载导出包
        </button>
      </div>
      <div className="card">
        <h2>操作审计</h2>
        <p className="page-desc">
          来自 <span className="mono">audit.jsonl</span> 的最近记录。不含密钥、不含参数原文。
        </p>
        {audit.length === 0 ? (
          <p className="page-desc">暂无审计事件。</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>事件</th>
                  <th>操作者</th>
                  <th>对象</th>
                  <th>备注</th>
                </tr>
              </thead>
              <tbody>
                {[...audit].reverse().slice(0, 40).map((ev, i) => (
                  <tr key={`${ev.at}-${ev.event}-${i}`}>
                    <td className="mono">{ev.at}</td>
                    <td>{ev.event}</td>
                    <td>{ev.actor_id || '—'}</td>
                    <td className="mono">{ev.target || '—'}</td>
                    <td>{ev.note || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="card">
        <h2>安全边界</h2>
        <ul className="page-desc">
          <li>本控制台无私钥；验签由 `agentshield verify` / GET /v1/receipts 完成。</li>
          <li>Bearer token 来自 loopback 的 /ui-config.json，只留在内存，刷新会再取一次。</li>
          <li>OpenShell verify 最高只到 readback_verified；filesystem/process 永不标 effective。</li>
        </ul>
      </div>
      {msg ? (
        <div className="notice" role="status">
          <p className="notice-title">结果</p>
          <p className="notice-detail">{msg}</p>
        </div>
      ) : null}
    </section>
  );
}
