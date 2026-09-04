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

  useEffect(() => {
    if (status?.enforcement_mode) setMode(status.enforcement_mode);
  }, [status?.enforcement_mode]);

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
        <h2>安全边界</h2>
        <ul className="page-desc">
          <li>本控制台无私钥；验签由 `agentshield verify` / GET /v1/receipts 完成。</li>
          <li>Bearer token 来自 loopback 的 /ui-config.json，只留在内存，刷新会再取一次。</li>
          <li>L3 OpenShell 探针尚未接入：不要把 filesystem/process 当成已 effective。</li>
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
