import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { LocalApiError, localApi } from '../api';
import type { Grant, LedgerAssetDetail, LedgerEvidence } from '../types';
import { useLocalSession } from '../session';
import {
  assetStatusLabel,
  assetStatusTag,
  grantStatusLabel,
  grantTag,
  platformLabel,
  shortHash,
  verdictLabel,
  verdictTag,
} from '../format';

interface Flash {
  kind: 'ok' | 'err';
  text: string;
}

export default function AgentDetailPage() {
  const { id } = useParams();
  const { actorId } = useLocalSession();
  const assetId = id ? decodeURIComponent(id) : '';
  const [asset, setAsset] = useState<LedgerAssetDetail | null>(null);
  const [card, setCard] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [platform, setPlatform] = useState('hermes');
  const [subject, setSubject] = useState(actorId);
  const [reason, setReason] = useState('');
  const [until, setUntil] = useState('');
  const [tools, setTools] = useState('');
  const [network, setNetwork] = useState('');
  const [fsRw, setFsRw] = useState('');
  const [models, setModels] = useState('');

  const fail = (err: unknown, fallback: string) =>
    setFlash({ kind: 'err', text: err instanceof Error ? err.message : fallback });
  const ok = (text: string) => setFlash({ kind: 'ok', text });

  const load = () => {
    if (!assetId) return;
    setLoading(true);
    localApi
      .asset(assetId)
      .then((data) => {
        setAsset(data);
        setError(null);
        setLoading(false);
        if (data.framework) setPlatform(data.framework);
        if (data.name) setSubject(data.name);
        if (data.admission_id) {
          localApi
            .admission(data.admission_id)
            .then((res) => setCard(res.skill_card || ''))
            .catch(() => setCard(''));
        } else {
          setCard('');
        }
      })
      .catch((err: unknown) => {
        setAsset(null);
        setError(err instanceof Error ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId]);

  const runAdmit = () => {
    if (!asset?.admit_path) return;
    setFlash(null);
    localApi
      .admit(asset.admit_path)
      .then((res) => {
        ok(`${res.admission.skill_name}：${verdictLabel(res.admission.verdict)}`);
        load();
      })
      .catch((err: unknown) => fail(err instanceof LocalApiError ? err : null, '准入失败'));
  };

  const createGrant = () => {
    if (!asset?.admission_id) return;
    setFlash(null);
    localApi
      .createGrant({
        admission_id: asset.admission_id,
        platform,
        subject_id: subject.trim() || actorId,
      })
      .then((res) => {
        ok(`已创建 ${res.grant.grant_id}（${grantStatusLabel(res.grant.status)}）。完整审批在签发页。`);
        load();
      })
      .catch((err: unknown) => fail(err, '签发失败'));
  };

  const confirm = () => {
    setFlash(null);
    localApi
      .confirmAsset(assetId, actorId)
      .then(() => {
        ok('已确认纳管');
        load();
      })
      .catch((err: unknown) => fail(err, '确认失败'));
  };

  const dismiss = () => {
    if (!reason.trim() || !until.trim()) {
      setFlash({ kind: 'err', text: '驳回需要原因和到期时间（RFC3339）' });
      return;
    }
    setFlash(null);
    localApi
      .dismissAsset(assetId, { actor_id: actorId, reason: reason.trim(), until: until.trim() })
      .then(() => {
        ok('已驳回');
        load();
      })
      .catch((err: unknown) => fail(err, '驳回失败'));
  };

  const patchPending = (grantId: string) => {
    const body: Record<string, unknown> = { actor_id: actorId };
    if (tools.trim()) body.tools = tools.split(/[\s,]+/).filter(Boolean);
    if (network.trim()) {
      body.network = network
        .split(/\n+/)
        .map((s) => s.trim())
        .filter(Boolean)
        .map((endpoint) => ({ endpoint, effect: 'allow' }));
    }
    if (fsRw.trim()) {
      body.filesystem = { read_only: [], read_write: fsRw.split(/[\s,]+/).filter(Boolean) };
    }
    if (models.trim()) body.models = models.split(/[\s,]+/).filter(Boolean);
    setFlash(null);
    localApi
      .grantAction(grantId, 'patch-desired', body)
      .then(() => {
        ok('已写入五域补丁，仍须人类批准');
        load();
      })
      .catch((err: unknown) => fail(err, '补丁失败'));
  };

  const evidenceCols: TableColumn<LedgerEvidence>[] = [
    {
      key: 'id',
      header: '证据',
      render: (e) => <span className="mono">{shortHash(e.evidence_id, 16)}</span>,
    },
    { key: 'type', header: '类型', render: (e) => e.source_type },
    {
      key: 'loc',
      header: '定位',
      render: (e) => <span className="mono">{e.source_locator}</span>,
    },
  ];

  const grantCols: TableColumn<Grant>[] = [
    { key: 'id', header: 'grant', render: (g) => <span className="mono">{g.grant_id}</span> },
    {
      key: 'st',
      header: '状态',
      render: (g) => (
        <span className={grantTag(g.status)} title={g.status}>
          {grantStatusLabel(g.status)}
        </span>
      ),
    },
    { key: 'plat', header: '平台', render: (g) => platformLabel(g.platform) },
    { key: 'sub', header: '主体', render: (g) => g.subject?.id ?? '—' },
  ];

  const permSubject = asset?.grants?.[0]?.subject?.id || asset?.name || '';
  const pendingGrant = asset?.grants?.find((g) => g.status === 'pending_approval');

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="agents"
        title={asset?.name ?? '智能体详情'}
        description="证据、声明工具、准入与签发。确认/驳回写入本地 assets/；批准前可补丁五域。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
      />
      <p className="page-desc">
        <Link to="/agents">← 返回资产列表</Link>
        {permSubject ? (
          <>
            {' · '}
            <Link to={`/permissions?subject_id=${encodeURIComponent(permSubject)}`}>
              查看该主体权限
            </Link>
          </>
        ) : null}
      </p>
      {error ? (
        <div className="notice" role="status">
          <p className="notice-title">无法加载资产</p>
          <p className="notice-detail">{error}</p>
        </div>
      ) : null}
      {flash ? (
        flash.kind === 'err' ? (
          <p className="action-error" role="alert">
            {flash.text}
          </p>
        ) : (
          <p className="sync-ok">{flash.text}</p>
        )
      ) : null}
      {asset ? (
        <>
          <div className="card">
            <h2>
              概况{' '}
              <span className={assetStatusTag(asset.status)}>{assetStatusLabel(asset.status)}</span>
            </h2>
            <dl className="kv-list">
              <dt>平台</dt>
              <dd>{platformLabel(asset.framework)}</dd>
              <dt>来源类型</dt>
              <dd>{asset.source_type}</dd>
              <dt>来源定位</dt>
              <dd>
                <span className="mono">{asset.source_locator}</span>
              </dd>
              <dt>准入路径</dt>
              <dd>
                <span className="mono">{asset.admit_path || '—'}</span>
              </dd>
              <dt>内容哈希</dt>
              <dd>
                <span className="mono">{shortHash(asset.content_hash, 16)}</span>
              </dd>
              <dt>声明工具</dt>
              <dd>
                {asset.declared_tools && asset.declared_tools.length > 0
                  ? asset.declared_tools.join(', ')
                  : '—'}
              </dd>
              <dt>准入裁决</dt>
              <dd>
                {asset.admission_verdict ? (
                  <span className={verdictTag(asset.admission_verdict)} title={asset.admission_verdict}>
                    {verdictLabel(asset.admission_verdict)}
                  </span>
                ) : (
                  '尚未准入'
                )}
              </dd>
              <dt>签发</dt>
              <dd>
                {asset.grant_status ? (
                  <span className={grantTag(asset.grant_status)} title={asset.grant_status}>
                    {grantStatusLabel(asset.grant_status)}
                  </span>
                ) : (
                  '—'
                )}
              </dd>
              {asset.hook_lost ? (
                <>
                  <dt>钩子</dt>
                  <dd>发现得到、当前无法阻断</dd>
                </>
              ) : null}
            </dl>
            <div className="toolbar toolbar-end">
              {asset.status === 'unadmitted' && asset.admit_path ? (
                <button type="button" className="btn btn-primary" onClick={runAdmit}>
                  运行 admit
                </button>
              ) : null}
              <button type="button" className="btn" onClick={confirm}>
                确认纳管
              </button>
            </div>
            <h3 className="block-gap">驳回该资产</h3>
            <p className="page-desc">驳回须给出原因与到期时间（RFC3339）；到期后回到待处理。</p>
            <div className="toolbar toolbar-end">
              <div className="field field-flush">
                <label htmlFor="dis-reason">驳回原因</label>
                <input id="dis-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
              </div>
              <div className="field field-flush">
                <label htmlFor="dis-until">到期（RFC3339）</label>
                <input
                  id="dis-until"
                  value={until}
                  onChange={(e) => setUntil(e.target.value)}
                  placeholder="2026-12-31T00:00:00Z"
                />
              </div>
              <button type="button" className="btn btn-danger" onClick={dismiss}>
                驳回
              </button>
            </div>
          </div>
          <div className="card">
            <h2>关联证据（{asset.evidence?.length ?? 0}）</h2>
            <SimpleTable
              columns={evidenceCols}
              rows={asset.evidence ?? []}
              rowKey={(e) => e.evidence_id}
              emptyText="暂无关联证据"
            />
          </div>
          <div className="card">
            <h2>关联签发</h2>
            <SimpleTable
              columns={grantCols}
              rows={asset.grants ?? []}
              rowKey={(g) => g.grant_id}
              emptyText="尚无 grant。准入通过后可在此起草签发。"
            />
            {asset.admission_verdict === 'quarantine' ? (
              <p className="page-desc block-gap">隔离件不能签发 grant。</p>
            ) : asset.admission_id ? (
              <div className="toolbar toolbar-end">
                <div className="field field-flush">
                  <label htmlFor="g-plat">平台</label>
                  <select
                    id="g-plat"
                    value={platform}
                    onChange={(e) => setPlatform(e.target.value)}
                  >
                    <option value="hermes">Hermes</option>
                    <option value="openclaw">OpenClaw</option>
                    <option value="codebuddy">CodeBuddy</option>
                  </select>
                </div>
                <div className="field field-flush">
                  <label htmlFor="g-sub">主体 ID</label>
                  <input id="g-sub" value={subject} onChange={(e) => setSubject(e.target.value)} />
                </div>
                <button type="button" className="btn btn-primary" onClick={createGrant}>
                  起草签发
                </button>
              </div>
            ) : (
              <p className="page-desc block-gap">先准入再签发。</p>
            )}
            {pendingGrant ? (
              <div className="block-gap">
                <h3>五域补丁（仅 pending_approval）</h3>
                <p className="page-desc">
                  filesystem / process 是静态域：写入后也不会显示为有效，仍须人批。补丁后到签发页批准。
                </p>
                <div className="field">
                  <label htmlFor="p-tools">工具（逗号分隔）</label>
                  <input id="p-tools" value={tools} onChange={(e) => setTools(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="p-net">网络 allow（每行 host:port）</label>
                  <textarea
                    id="p-net"
                    rows={3}
                    value={network}
                    onChange={(e) => setNetwork(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="p-fs">文件系统读写路径（逗号分隔，静态域不生效）</label>
                  <input id="p-fs" value={fsRw} onChange={(e) => setFsRw(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="p-models">模型</label>
                  <input id="p-models" value={models} onChange={(e) => setModels(e.target.value)} />
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => patchPending(pendingGrant.grant_id)}
                >
                  写入补丁
                </button>
              </div>
            ) : null}
          </div>
          {card ? (
            <div className="card">
              <h2>Skill Card</h2>
              <pre className="skill-card-pre">{card}</pre>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
