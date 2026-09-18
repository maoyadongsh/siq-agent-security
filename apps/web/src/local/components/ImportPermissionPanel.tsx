import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { localApi } from '../api';
import { newImportId, skillImportErrorText } from '../skillImports';
import { useLocalSession } from '../session';
import type { AdapterInstance, ImportPermissionRequest, SkillImportResult } from '../types';

export default function ImportPermissionPanel({ result }: { result: SkillImportResult }) {
  const navigate = useNavigate();
  const { actorId, setActorId } = useLocalSession();
  const [instances, setInstances] = useState<AdapterInstance[]>([]);
  const [instance, setInstance] = useState('');
  const [loading, setLoading] = useState(true);
  const [epoch, setEpoch] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<ImportPermissionRequest | null>(null);
  const active = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    let canceled = false;
    setLoading(true); setError(null);
    const controller = new AbortController();
    Promise.allSettled(['hermes', 'openclaw', 'workbuddy'].map(async (platform) => {
      const catalog = await localApi.adapterInstances(platform);
      if (platform !== 'workbuddy') return catalog.instances.filter((item) => item.detected);
      const available = await Promise.all(catalog.instances.filter((item) => item.detected).map(async (item) => {
        try {
          const targets = await localApi.skillInstallationTargets(item.instance_id, controller.signal);
          return targets.targets.some((target) => target.available) ? item : null;
        } catch { return null; }
      }));
      return available.filter((item): item is AdapterInstance => item !== null);
    })).then((catalogs) => {
      if (!canceled) {
        const found = catalogs.flatMap((entry) => entry.status === 'fulfilled' ? entry.value : []);
        setInstances(found); setInstance((previous) => found.some((item) => item.instance_id === previous) ? previous : '');
        if (catalogs.some((entry) => entry.status === 'rejected')) setError('部分平台实例暂时无法读取，已保留可核验的目标；可刷新重试。');
      }
    }).finally(() => { if (!canceled) setLoading(false); });
    return () => { canceled = true; controller.abort(); };
  }, [epoch]);
  const prepare = async (original?: ImportPermissionRequest) => {
    if (submitting.current || busy || loading) return;
    const body: ImportPermissionRequest = original ?? {
      schema_version: 'local-skill-import-permission-create/v1', request_id: newImportId().replace(/^si-/, 'ip-'),
      artifact_digest: result.import.artifact_digest, analysis_sha256: result.import.analysis_sha256,
      instance_id: instance, actor_id: actorId.trim(),
    };
    if (!body.instance_id || !body.actor_id || !instances.some((item) => item.instance_id === body.instance_id)) return;
    submitting.current = true; setBusy(true); setPending(body); setError(null);
    const controller = new AbortController(); active.current = controller;
    try {
      const prepared = await localApi.prepareImportPermissions(result.import.import_id, body, controller.signal);
      if (prepared.grant.platform !== instances.find((item) => item.instance_id === body.instance_id)?.platform) throw new Error('skill_install_incompatible_response');
      if (!controller.signal.aborted) navigate(`/grants?grant=${encodeURIComponent(prepared.grant.grant_id)}`);
    } catch (err) { if (!controller.signal.aborted) setError(skillImportErrorText(err)); }
    finally { submitting.current = false; if (!controller.signal.aborted) setBusy(false); }
  };
  return <section className="import-permission-panel" aria-labelledby="prepare-permissions-heading">
    <h3 id="prepare-permissions-heading">为目标智能体准备权限</h3>
    <p className="page-desc">选择已有 Hermes、OpenClaw 或受支持的 Windows WorkBuddy 实例，生成待审阅的权限草稿。下一页可调整权限和期限，再由你批准；批准后仍需确认安装与实例权限。</p>
    <p className="page-desc">WorkBuddy 仅在本机服务返回可用 Windows 安装目标后列出。安装时还需明确选择用户级或已登记项目；准备权限不会安装或启用 Skill。</p>
    <div className="field"><label htmlFor="import-target-instance">目标智能体实例</label>
      <select id="import-target-instance" value={instance} disabled={loading || busy || !!pending}
        onChange={(event) => setInstance(event.target.value)}>
        <option value="">请选择目标实例</option>
        {instances.map((item) => <option key={`${item.platform}:${item.instance_id}`} value={item.instance_id}>{item.platform} · {item.name} · {item.config_dir}</option>)}
      </select></div>
    <div className="field"><label htmlFor="import-permission-actor">权限准备操作者</label>
      <input id="import-permission-actor" value={actorId} onChange={(event) => setActorId(event.target.value)} maxLength={128} disabled={busy || !!pending} /></div>
    {loading ? <p role="status">正在读取实例…</p> : !instances.length ? <p className="page-desc">未发现可用目标实例。请先完成平台初始化；WorkBuddy 还需可安全读取的用户目录或已登记项目，再刷新列表。</p> : null}
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    {busy ? <p role="status">正在复验候选并准备权限…</p> : null}
    <div className="import-actions">
      {!pending ? <button className="btn btn-primary" type="button" disabled={busy || loading || !instance || !actorId.trim()} onClick={() => void prepare()}>准备并审阅权限</button> : null}
      {pending && error ? <>
        <button className="btn" type="button" disabled={busy} onClick={() => void prepare(pending)}>查询或重试原权限请求</button>
        <button className="btn" type="button" disabled={busy} onClick={() => { setPending(null); setError(null); }}>重新选择目标</button>
      </> : null}
      {!pending ? <button className="btn" type="button" disabled={busy || loading} onClick={() => setEpoch((n) => n + 1)}>刷新实例</button> : null}
    </div>
  </section>;
}
