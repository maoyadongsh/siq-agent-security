import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { api, ApiError, describeApiError } from '@/api/client';
import type { AgentAsset, Evidence } from '@/api/types';

type LoadStatus = 'loading' | 'connected' | 'disconnected';

const statusTag: Record<string, string> = {
  managed: 'tag-ok',
  confirmed: 'tag-ok',
  stale: 'tag-warn',
  candidate: 'tag-warn',
  needs_review: 'tag-warn',
  dismissed: 'tag-err',
  retired: '',
};

const evidenceColumns: TableColumn<Evidence>[] = [
  { key: 'id', header: '证据 ID', render: (e) => <span className="mono">{e.id}</span> },
  { key: 'source_type', header: '来源类型', render: (e) => e.source_type },
  {
    key: 'source_locator',
    header: '来源定位',
    render: (e) => <span title={e.source_locator}>{e.source_locator}</span>,
  },
  { key: 'observed_at', header: '观察时间', render: (e) => e.observed_at },
  { key: 'classification', header: '分类', render: (e) => e.classification },
  {
    key: 'content_hash',
    header: '内容摘要',
    render: (e) => <span className="mono">{e.content_hash.slice(0, 16)}…</span>,
  },
  { key: 'collector_id', header: '采集者', render: (e) => e.collector_id },
];

/** 资产信息行 */
function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

/**
 * 智能体资产详情：拉取 GET /agents/:id 与 GET /agents/:id/evidence 渲染。
 * 后端未运行时保持"未连接"空态（可重试），不阻塞页面。
 */
export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<AgentAsset | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [reloadSeq, setReloadSeq] = useState(0);

  useEffect(() => {
    if (!id) {
      setStatus('disconnected');
      setError('缺少资产 ID');
      return;
    }
    let cancelled = false;
    setStatus('loading');
    setError(null);

    Promise.allSettled([api.getAgent(id), api.getAgentEvidence(id)]).then(
      ([assetResult, evidenceResult]) => {
        if (cancelled) return;
        if (assetResult.status === 'rejected') {
          setStatus('disconnected');
          setError(describeApiError(assetResult.reason, '资产详情加载失败'));
          return;
        }
        setAgent(assetResult.value);
        setEvidence(
          evidenceResult.status === 'fulfilled' ? evidenceResult.value : [],
        );
        setStatus('connected');
      },
    );

    return () => {
      cancelled = true;
    };
  }, [id, reloadSeq]);

  return (
    <section>
      <PageHeader
        title={agent?.name ?? '智能体资产详情'}
        description="查看资产来源、纳管状态、角色、运行边界与关联证据。"
        connection={status}
        connectionError={error}
      />
      {status === 'disconnected' ? (
        <DisconnectedNotice error={error} onRetry={() => setReloadSeq((s) => s + 1)} />
      ) : null}
      {status === 'loading' ? (
        <p className="table-empty">加载中…</p>
      ) : null}
      {status === 'connected' && agent ? (
        <>
          <div className="card">
            <h2>资产信息</h2>
            <dl className="kv-list">
              <InfoRow label="资产 ID" value={<span className="mono">{agent.id}</span>} />
              <InfoRow label="名称" value={agent.name} />
              <InfoRow label="角色" value={agent.role ?? '—'} />
              <InfoRow
                label="状态"
                value={
                  <span className={`tag ${statusTag[agent.status] ?? ''}`}>
                    {agent.status}
                  </span>
                }
              />
              <InfoRow label="框架" value={agent.framework} />
              <InfoRow label="系统" value={agent.system_id ?? '—'} />
              <InfoRow label="负责人" value={agent.owner_user_id ?? '—'} />
              <InfoRow label="来源类型" value={agent.source_type ?? '—'} />
              <InfoRow
                label="来源定位"
                value={<span className="mono">{agent.source_locator ?? '—'}</span>}
              />
              <InfoRow label="更新时间" value={agent.updated_at} />
            </dl>
          </div>
          <div className="card">
            <h2>关联证据（{evidence.length}）</h2>
            <SimpleTable
              columns={evidenceColumns}
              rows={evidence}
              rowKey={(e) => e.id}
              emptyText="暂无关联证据"
            />
          </div>
          <PermissionGovernance assetId={id ?? ""} assetName={agent.name} />
        </>
      ) : null}
      <p>
        <Link to="/agents">← 返回智能体资产列表</Link>
      </p>
    </section>
  );
}


/** 权限管控（§20.2 + 诚实边界 §6.5）：
 * - enforce 徽标：enforced=真实强制（effective 部署）；declared_only=⚠️声明未强制；
 * - 五域精细编辑器：文件读写路径 / 网络端点 / 进程身份 / 工具 / 模型 → 生成 Desired Policy；
 * - 策略与部署列表（部署目标沙箱）。 */
function PermissionGovernance({ assetId, assetName }: { assetId: string; assetName: string }) {
  const [enf, setEnf] = useState<Awaited<ReturnType<typeof api.getAgentEnforcement>> | null>(null);
  const [policies, setPolicies] = useState<Awaited<ReturnType<typeof api.getAgentPolicies>>>([]);
  const [fsRO, setFsRO] = useState('/etc,/usr,/lib');
  const [fsRW, setFsRW] = useState('/sandbox,/tmp');
  const [network, setNetwork] = useState('');
  const [tools, setTools] = useState('');
  const [models, setModels] = useState('');
  const [mode, setMode] = useState<'audit_only' | 'warn' | 'block'>('block');
  const [formMsg, setFormMsg] = useState<string | null>(null);
  const [formErr, setFormErr] = useState<string | null>(null);

  const load = () => {
    api
      .getAgentEnforcement(assetId)
      .then(setEnf)
      .catch(() => setEnf(null));
    api
      .getAgentPolicies(assetId)
      .then(setPolicies)
      .catch(() => setPolicies([]));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId]);

  const onCreatePolicy = async () => {
    setFormErr(null);
    setFormMsg(null);
    try {
      const body: Record<string, unknown> = {
        name: `agent-${assetName}-policy`,
        selector: { agent_ids: [assetId] },
        enforcement_mode: mode,
      };
      if (fsRO || fsRW) {
        body.filesystem = {
          read_only: fsRO.split(',').map((s) => s.trim()).filter(Boolean),
          read_write: fsRW.split(',').map((s) => s.trim()).filter(Boolean),
        };
      }
      if (network.trim()) {
        body.network = network
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean)
          .map((endpoint) => ({ endpoint, effect: 'allow', binary_paths: ['/usr/bin/curl'], purpose: 'web-edited' }));
      }
      if (tools.trim()) body.tools = tools.split(',').map((s) => s.trim()).filter(Boolean);
      if (models.trim()) body.model_routing = { allowed_models: models.split(',').map((s) => s.trim()).filter(Boolean) };
      await api.createPolicy(body);
      setFormMsg('策略已创建——请到「变更中心」审批并部署到该智能体的沙箱');
      load();
    } catch (err) {
      setFormErr(err instanceof ApiError ? err.message : '创建失败');
    }
  };

  return (
    <div className="card">
      <h2>
        权限管控{' '}
        {enf && (
          <span className={`state-tag ${enf.enforce_status === 'enforced' ? 'effective' : 'unknown'}`}>
            {enf.enforce_status === 'enforced' ? '已强制（OpenShell）' : '声明未强制'}
          </span>
        )}
      </h2>

      {enf && enf.enforce_status === 'declared_only' && (
        <p className="page-desc">
          该智能体尚无生效部署。权限调整会先保存为期望策略；只有完成沙箱部署并通过回读验证后，控制项才会进入强制状态。
        </p>
      )}
      {enf && enf.all_deployments.length > 0 && (
        <p className="page-desc">
          部署记录：{enf.all_deployments.map((d) => `${d.target}(${d.status})`).join('、')}
        </p>
      )}

      <div className="form-box">
        <label>
          文件只读路径（逗号分隔）
          <input value={fsRO} onChange={(e) => setFsRO(e.target.value)} />
        </label>
        <label>
          文件可写路径（逗号分隔）
          <input value={fsRW} onChange={(e) => setFsRW(e.target.value)} />
        </label>
        <label>
          网络端点（每行一个 host:port）
          <textarea rows={3} value={network} onChange={(e) => setNetwork(e.target.value)} placeholder="api.example.com:443" />
        </label>
        <label>
          工具（逗号分隔）
          <input value={tools} onChange={(e) => setTools(e.target.value)} placeholder="document.read,model.generate" />
        </label>
        <label>
          允许模型（逗号分隔）
          <input value={models} onChange={(e) => setModels(e.target.value)} placeholder="MiniMax-M3" />
        </label>
        <label>
          执行档位
          <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
            <option value="audit_only">仅审计</option>
            <option value="warn">告警</option>
            <option value="block">阻断</option>
          </select>
        </label>
        <button className="btn-sm btn-primary" onClick={onCreatePolicy}>
          生成期望策略
        </button>
        {formMsg && <span className="sync-ok">{formMsg}</span>}
        {formErr && <span className="sync-err">{formErr}</span>}
      </div>

      {policies.length > 0 && (
        <div className="card">
          <h3>已有策略</h3>
          <SimpleTable
            columns={[
              { key: 'name', header: '名称', render: (p) => p.name },
              { key: 'version', header: '版本', render: (p) => `v${p.version}` },
              { key: 'enforcement_mode', header: '档位', render: (p) => p.enforcement_mode },
              { key: 'status', header: '状态', render: (p) => p.status },
            ]}
            rows={policies}
            rowKey={(p) => p.id}
          />
          <p className="page-desc">
            <Link to="/changes">→ 到变更中心审批并部署</Link>
          </p>
        </div>
      )}
    </div>
  );
}
