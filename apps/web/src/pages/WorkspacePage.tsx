import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import { useConsoleContext } from '@/components/ConsoleContext';
import { canVisit } from '@/api/consoleContext';

const entries = [
  { to: '/environments', title: '环境与设备', description: '继续接入设备，核对心跳与发现结果。' },
  { to: '/agents?view=candidates', title: '智能体与候选', description: '查看框架配置、业务用途与已确认资产。' },
  { to: '/permissions', title: '权限事实', description: '区分声明、观测与已核验的权限。' },
  { to: '/findings', title: '风险记录', description: '查看检测结果和处置记录。' },
  { to: '/policies', title: '策略清单', description: '查看期望策略与当前状态。' },
  { to: '/changes', title: '变更与审批', description: '查看变更状态；是否可以批准取决于操作权限。' },
  { to: '/audit', title: '审计记录', description: '查看本组织操作记录与处理依据。' },
];
export default function WorkspacePage() {
  const { data, status, reload } = useConsoleContext();
  return <section className="enterprise-workspace">
    <PageHeader icon="overview" title="工作台" description="核对当前组织与角色，从你有权访问的入口开始。"
      connection={status === 'ready' ? 'connected' : status === 'loading' ? 'loading' : 'disconnected'}
      actions={<button className="btn" disabled={status === 'loading'} onClick={reload}>{status === 'loading' ? '正在核对…' : '刷新组织与权限'}</button>} />
    {status === 'loading' ? <p role="status">正在核对组织与访问权限…</p> : null}
    {status === 'error' ? <p role="alert">暂时无法核对组织与权限，旧入口已撤下。请刷新重试；持续失败时联系组织管理员。</p> : null}
    {data ? <>
      <section className="card" aria-label="当前组织与角色">
        <h2>{data.tenant.name || '组织名称尚未同步'}</h2>
        <p>{data.actor.type === 'service' ? '当前为服务身份。' : '当前为用户身份。'}{data.authentication === 'development_headers' ? ' 当前使用开发身份，仅用于联调，不能作为生产登录证明。' : '身份来自已验证的访问凭证。'}</p>
        <h3>当前角色</h3>
        {data.roles.length ? <ul>{data.roles.map(role => <li key={role.code}><strong>{role.label}</strong>：{role.description}</li>)}</ul> : <p>没有产品内置角色，以下入口按实际权限显示。</p>}
        {data.custom_role_count > 0 ? <p>另有 {data.custom_role_count} 个自定义角色，权限以本次核对结果为准。</p> : null}
        <p>角色说明帮助理解职责，实际操作仍由服务端逐次检查。</p>
        <details><summary>身份标识与核对时间</summary><dl className="kv-list"><dt>组织标识</dt><dd>{data.tenant.id}</dd><dt>账号标识</dt><dd>{data.actor.id}</dd><dt>核对时间</dt><dd>{new Date(data.evaluated_at).toLocaleString('zh-CN', { hour12: false })}</dd></dl></details>
      </section>
      <section className="card" aria-label="可用工作入口">
        <h2>开始处理</h2>
        <div className="quick-grid">{entries.filter(entry => canVisit(data, entry.to)).map(entry => <Link key={entry.to} className="quick-tile" to={entry.to}><span className="quick-tile-text"><strong className="quick-tile-title">{entry.title}</strong><span className="quick-tile-desc">{entry.description}</span></span></Link>)}</div>
        {!entries.some(entry => canVisit(data, entry.to)) ? <p>当前账号尚无业务页面读取权限，请联系组织管理员开通所需范围。</p> : null}
        {data.actions.approve_change && !data.access.changes ? <p role="status">你具有变更批准权限，但缺少查看变更清单所需的策略读取权限。请联系组织管理员补齐读取权限后再处理。</p> : null}
      </section>
      <section className="card"><h2>需要更多权限</h2><p>请向所属组织管理员说明需要操作的环境、智能体及用途，由管理员在组织身份系统中调整授权。此处不会自动申请或批准权限；权限调整后重新登录，再刷新本页核对。</p><Link to="/settings">查看连接设置</Link></section>
    </> : null}
  </section>;
}
