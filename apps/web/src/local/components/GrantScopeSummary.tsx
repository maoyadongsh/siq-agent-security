import { grantStatusLabel } from '../format';
import type { Grant } from '../types';
const scopeLabel = (domain: string, action: string) => {
  if (domain === 'filesystem') return action === 'fs.read' ? '只读目录' : action === 'fs.write' ? '读写目录' : `文件操作 ${action}`;
  return ({ tool: '工具', network: '网络端点', model: '模型声明', credential: '凭据', process: '进程', resource: '资源' } as Record<string, string>)[domain] ?? domain;
};
export default function GrantScopeSummary({ grant, label }: { grant?: Grant; label: string }) {
  return grant ? <details open><summary>{label} · {grantStatusLabel(grant.status)}</summary>
    <ul>{(grant.facts ?? []).map((fact) => <li key={fact.fact_id}>{fact.effect === 'deny' ? '拒绝' : '允许'} · {scopeLabel(fact.domain, fact.action)} · {fact.resource.value}{fact.conditions?.require_approval ? ' · 每次需确认' : ''}</li>)}</ul>
    <p>授权到期：{grant.expires_at ? new Date(grant.expires_at).toLocaleString() : '未设置到期时间'}</p>
  </details> : null;
}
