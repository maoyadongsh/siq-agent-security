import { useCallback, useEffect, useState } from 'react';
import Modal from '@/components/Modal';
import { LocalApiError, localApi } from '../api';
import { useLocalSession } from '../session';
import type { Grant, GrantResourceEdit } from '../types';

interface Draft { tools: string; readOnly: string; readWrite: string; networkAllow: string; networkDeny: string; models: string }
const empty: Draft = { tools: '', readOnly: '', readWrite: '', networkAllow: '', networkDeny: '', models: '' };
function fromGrant(grant: Grant): Draft {
  const facts = grant.facts ?? [];
  const values = (domain: string, effect = 'allow', action?: string) => Array.from(new Set(facts.filter(
    (f) => f.domain === domain && f.effect === effect && (!action || f.action === action),
  ).map((f) => f.resource.value))).join('\n');
  const tools = Array.from(new Set([...facts.filter((f) => f.domain === 'tool' && f.effect === 'allow').map((f) => f.resource.value),
    ...(grant.hermes_toolset_allowlist ?? []), ...(grant.openclaw_tool_policy?.allow ?? [])])).join('\n');
  return { tools, readOnly: values('filesystem', 'allow', 'fs.read'),
    readWrite: values('filesystem', 'allow', 'fs.write'), networkAllow: values('network'),
    networkDeny: values('network', 'deny'), models: values('model') };
}
const lines = (text: string) => text.split(/\r?\n/).map((v) => v.trim()).filter(Boolean);

export default function GrantResourceDialog({ grantId, onClose, onSaved }: {
  grantId: string; onClose: () => void; onSaved: (grant: Grant) => void;
}) {
  const { actorId, setActorId } = useLocalSession();
  const [editorActor, setEditorActor] = useState(actorId);
  const [grant, setGrant] = useState<Grant | null>(null);
  const [draft, setDraft] = useState<Draft>(empty);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const close = useCallback(() => { if (!busy) onClose(); }, [busy, onClose]);
  useEffect(() => {
    let active = true;
    setLoading(true); setLoadFailed(false); setError('');
    localApi.grant(grantId).then(({ grant: current }) => {
      if (active) { setGrant(current); setDraft(fromGrant(current)); setLoading(false); }
    }).catch(() => { if (active) { setLoadFailed(true); setError('无法读取当前权限，请检查连接后重试。'); setLoading(false); } });
    return () => { active = false; };
  }, [grantId, retry]);
  const editable = grant?.status === 'pending_approval' && !loading && !loadFailed && !busy;
  const update = (key: keyof Draft, value: string) => setDraft((current) => ({ ...current, [key]: value }));
  const save = async () => {
    if (!editable || !grant || grant.state_revision === undefined || !editorActor.trim()) return;
    setError('');
    const values = Object.values(draft).map(lines);
    if (values.some((items) => items.length > 32 || new Set(items).size !== items.length)) {
      setError('每个列表最多 32 项，不能重复；目录包含空格时仍完整写在一行。'); return;
    }
    if (lines(draft.networkAllow).length + lines(draft.networkDeny).length > 32) {
      setError('网络允许与拒绝列表合计最多 32 项。'); return;
    }
    const resources: GrantResourceEdit = { tools: lines(draft.tools),
      filesystem: { read_only: lines(draft.readOnly), read_write: lines(draft.readWrite) },
      network: [...lines(draft.networkAllow).map((endpoint) => ({ endpoint, effect: 'allow' as const })),
        ...lines(draft.networkDeny).map((endpoint) => ({ endpoint, effect: 'deny' as const }))], models: lines(draft.models) };
    setBusy(true);
    try {
      const saved = await localApi.setGrantResources(grantId, grant.state_revision, editorActor.trim(), resources);
      setActorId(editorActor.trim());
      onSaved({ ...saved.grant, state_revision: saved.state_revision });
    } catch (err) {
      setError(err instanceof LocalApiError && err.status === 409
        ? '权限已被其他操作修改或已批准。你的输入仍保留；重新读取会载入最新权限，请核对后再编辑。'
        : '保存未完成。请检查目录为规范的绝对路径、网络为主机:端口，以及每个列表最多 32 项。');
    } finally { setBusy(false); }
  };
  const field = (key: keyof Draft, label: string, hint?: string) => <div className="field" key={key}>
    <label htmlFor={`grant-resource-${key}`}>{label}</label>
    <textarea id={`grant-resource-${key}`} rows={3} disabled={!editable} value={draft[key]}
      onChange={(event) => update(key, event.target.value)} aria-describedby={hint ? `grant-resource-${key}-hint` : undefined} />
    {hint ? <p className="page-desc" id={`grant-resource-${key}-hint`}>{hint}</p> : null}
  </div>;
  const preserved = (grant?.facts ?? []).filter((f) =>
    ['credential', 'process', 'resource'].includes(f.domain) ||
    (['tool', 'filesystem', 'model'].includes(f.domain) && f.effect === 'deny') || f.conditions?.require_approval);
  return <Modal open className="grant-resource-modal" title="编辑权限范围" description="保存只更新待批准授权；检查范围后，需要再次人工批准。" onClose={close}>
    <div className="modal-body adapter-change-body" aria-busy={loading || busy}>
      {loading ? <p role="status">正在读取当前授权…</p> : null}
      {grant ? <>
        <p>平台：{grant.platform} · 主体：{grant.subject.id}</p>
        <p>来源准入：{grant.admission_id}</p>
        <p className="page-desc">此授权尚未证明每次调用的 Skill 归属。目录限制是工具层检查，不代表操作系统隔离。</p>
        {grant.status !== 'pending_approval' ? <p role="status">此授权已离开待批准状态。需要修改时，请重新起草并批准。</p> : null}
        <div className="toolbar">
          <button type="button" className="btn btn-sm" disabled={!editable} onClick={() => setDraft((current) => ({
            ...current, readOnly: Array.from(new Set([...lines(current.readOnly), ...lines(current.readWrite)])).join('\n'), readWrite: '',
          }))}>目录全部改为只读</button>
          <button type="button" className="btn btn-sm" disabled={!editable} onClick={() => setDraft((current) => ({ ...empty, networkDeny: current.networkDeny }))}>清空允许范围</button>
        </div>
        <p className="page-desc">每行一项，留空表示清空对应允许列表。路径中的空格和逗号会保留。</p>
        {field('tools', '允许的工具', '仅填写平台实际工具名称；允许工具不等于允许任意资源。')}
        {field('readOnly', '只读目录', '当前填写绝对 POSIX 路径，例如 /home/me/reports；Windows 原生路径尚待接入验证。')}
        {field('readWrite', '读写目录', '允许读取、修改和删除范围内的文件；不会授予凭据读取权限。')}
        {field('networkAllow', '允许的网络端点', '例如 api.example.com:443；子域可写 *.example.com:443。')}
        {field('networkDeny', '拒绝的网络端点', '拒绝优先于允许。端口必须明确，不支持在此填写 URL 路径。')}
        {field('models', '允许的模型声明', '声明是否由宿主执行需另行验证；保存不能证明模型路由已受控。')}
        <details><summary>保留的限制与批准条件（{preserved.length} 项）</summary>
          <ul>{preserved.map((f) => <li key={f.fact_id}>{f.domain} · {f.resource.value}{f.conditions?.require_approval ? ' · 保留该工具时仍需人工确认' : ' · 保留限制'}</li>)}</ul>
          {grant.openclaw_tool_policy?.deny?.length ? <p>平台策略中的工具拒绝：{grant.openclaw_tool_policy.deny.join('、')}</p> : null}
          {grant.openclaw_tool_policy?.require_approval?.length ? <p>平台策略中的人工确认条件：{grant.openclaw_tool_policy.require_approval.join('、')}；保留这些工具时继续生效。</p> : null}
        </details>
        <div className="field"><label htmlFor="grant-resource-actor">本次修改人</label>
          <input id="grant-resource-actor" maxLength={128} value={editorActor} disabled={busy} onChange={(e) => setEditorActor(e.target.value)} /></div>
      </> : null}
      {error ? <p role="alert" className="action-error">{error}</p> : null}
    </div>
    <div className="modal-actions runtime-check-actions">
      <button type="button" className="btn" disabled={busy} onClick={onClose}>取消</button>
      <button type="button" className="btn" disabled={busy || loading} onClick={() => setRetry((n) => n + 1)}>重新读取</button>
      <button type="button" className="btn btn-primary" disabled={!editable || !editorActor.trim()} onClick={save}>保存待批准权限</button>
    </div>
  </Modal>;
}
