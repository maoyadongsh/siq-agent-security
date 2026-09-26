/**
 * 框架配置实例—角色只读树视图（ENT-018-FRAMEWORK-TREE-UI）。
 *
 * 边界：
 * - 仅在打开本视图后请求 GET /api/v1/framework-role-inventory（只读，无写操作）；
 * - 需要 ConsoleContext 的 agents + environments 两项访问权限；身份加载中/失败/
 *   权限不足时不发请求、不显示旧身份数据；
 * - 展示的是「历史配置来源」分组，不代表进程运行、技能安装或权限生效；
 * - 同名角色不去重；实例分组键含 环境+设备+framework+instance_key；
 * - 分页为显式「加载更多」，不自动拉取全部页。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { frameworkTreeQuery } from './frameworkTreeNavigation';
import { ApiError, describeApiError } from '@/api/client';
import {
  getFrameworkRoleInventory,
  type FrameworkRoleInventoryItem,
} from '@/api/frameworkRoleInventory';
import { assetStatusLabel } from '@/api/inventoryReview';
import { useConsoleContext } from '@/components/ConsoleContext';
import {
  groupFrameworkRoles,
  type DeviceGroup,
  type EnvironmentGroup,
  type InstanceGroup,
  type RoleEntry,
} from './frameworkTree';
import './framework-tree.css';

function RoleRow({ entry }: { entry: RoleEntry }) {
  const [params] = useSearchParams();
  const { item } = entry;
  const source = item.framework_source.source;
  return <li className="framework-tree-role">
    <span className="framework-tree-role-name">{item.name || '（未命名角色）'}</span>
    <span className="tag">{assetStatusLabel(item.asset_status)}</span>
    <code className="mono framework-tree-role-id">{item.asset_id}</code>
    <Link to={`/agents/${encodeURIComponent(item.asset_id)}?${frameworkTreeQuery(params)}`}>查看详情</Link>
    {entry.conflict
      ? <span className="tag tag-err">不同响应内容不一致，需刷新核对</span>
      : null}
    {source ? <details className="framework-tree-evidence">
      <summary>本角色来源与证据标识</summary>
      <dl className="kv-list">
        <dt>配置摘要</dt><dd className="mono">{source.config_sha256}</dd>
        <dt>证据 ID</dt><dd className="mono">{source.evidence_id}</dd>
        <dt>观察 ID</dt><dd className="mono">{source.observation_id}</dd>
        <dt>观察时间</dt><dd><time dateTime={source.observed_at}>{source.observed_at}</time></dd>
      </dl>
      <p className="framework-tree-note">只对应本角色的历史来源；同实例其他角色的配置观察可能不同，不作为整组共同证据。</p>
    </details> : null}
  </li>;
}

function RoleList({ roles }: { roles: RoleEntry[] }) {
  return <ul className="framework-tree-roles">
    {roles.map(entry => <RoleRow key={entry.item.asset_id} entry={entry} />)}
  </ul>;
}

function InstanceDisclosure({ group }: { group: InstanceGroup }) {
  return <details className="framework-tree-instance">
    <summary>
      <span>{group.framework === 'hermes' ? 'Hermes profile' : 'OpenClaw 配置实例'} <code className="mono">{group.instanceKey}</code></span>
      <span className="framework-tree-count">已加载 {group.roles.length} 个角色（非完整清单）</span>
    </summary>
    <p className="framework-tree-note">
      历史配置来源：不代表进程正在运行，运行状态未验证；技能安装关系待确认；有效权限本视图无证据（不代表无权限）。
    </p>
    <RoleList roles={group.roles} />
  </details>;
}

function DeviceDisclosure({ device }: { device: DeviceGroup }) {
  const roleCount = device.instances.reduce((total, group) => total + group.roles.length, 0);
  return <details className="framework-tree-device">
    <summary>
      <span>设备 <code className="mono">{device.deviceId}</code></span>
      <span className="framework-tree-count">
        {device.deviceRevoked ? '设备凭据已吊销，仅保留历史' : '设备凭据未吊销，不代表当前在线'}
        {' · '}已加载 {device.instances.length} 个实例 / {roleCount} 个角色
      </span>
    </summary>
    {device.instances.map(group => <InstanceDisclosure key={group.key} group={group} />)}
  </details>;
}

function EnvironmentDisclosure({ environment }: { environment: EnvironmentGroup }) {
  const instanceCount = environment.devices.reduce((total, device) => total + device.instances.length, 0);
  return <details className="framework-tree-env">
    <summary>
      <span>环境 <code className="mono">{environment.environmentId}</code></span>
      <span className="framework-tree-count">已加载 {environment.devices.length} 台设备 / {instanceCount} 个实例</span>
    </summary>
    {environment.devices.map(device => <DeviceDisclosure key={device.deviceId} device={device} />)}
  </details>;
}

function UnknownSourceSection({ title, note, roles }: { title: string; note: string; roles: RoleEntry[] }) {
  if (!roles.length) return null;
  return <details className="framework-tree-unknown">
    <summary>
      <span>{title}</span>
      <span className="framework-tree-count">已加载 {roles.length} 个角色</span>
    </summary>
    <p className="framework-tree-note">{note}</p>
    <RoleList roles={roles} />
  </details>;
}

function FrameworkTreeResults({ environmentId, deviceId }: { environmentId: string; deviceId: string }) {
  const [rows, setRows] = useState<FrameworkRoleInventoryItem[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState('');
  // 请求序号：刷新/过滤切换后，迟到响应不得覆盖新结果。
  const seq = useRef(0);
  // 已使用的游标：防止服务端重复游标造成死循环或重复请求。
  const usedCursors = useRef<Set<string>>(new Set());

  useEffect(() => {
    const ticket = ++seq.current;
    usedCursors.current = new Set();
    getFrameworkRoleInventory({
      environmentId: environmentId || undefined,
      deviceId: deviceId || undefined,
    }).then(page => {
      if (ticket !== seq.current) return;
      if (page.next_cursor !== null) usedCursors.current.add(page.next_cursor);
      setRows(page.items);
      setNextCursor(page.next_cursor);
      setStatus('ready');
    }).catch((reason: unknown) => {
      if (ticket !== seq.current) return;
      setRows([]);
      setNextCursor(null);
      setStatus('error');
      setError(reason instanceof ApiError && reason.status === 403
        ? '当前账号缺少资产或环境读取权限，请联系组织管理员。'
        : describeApiError(reason, '框架角色清单读取失败，不能据此判断没有框架实例。'));
    });
    return () => { seq.current += 1; };
  }, [environmentId, deviceId]);

  const loadPage = (cursor: string | undefined, append: boolean) => {
    const ticket = ++seq.current;
    if (append) {
      setLoadingMore(true);
      setMoreError('');
    } else {
      setStatus('loading');
      setError('');
    }
    getFrameworkRoleInventory({
      environmentId: environmentId || undefined,
      deviceId: deviceId || undefined,
      cursor,
    }).then(page => {
      if (ticket !== seq.current) return;
      if (page.next_cursor !== null) {
        if (usedCursors.current.has(page.next_cursor)) {
          // 重复游标：停止分页，已加载记录保留并明确提示，不循环请求。
          setNextCursor(null);
          setLoadingMore(false);
          if (append) setMoreError('分页游标异常（重复游标），已停止继续加载；已加载记录保留。');
          else { setRows([]); setStatus('error'); setError('分页游标异常（重复游标），请刷新重试。'); }
          return;
        }
        usedCursors.current.add(page.next_cursor);
      }
      setRows(previous => append ? [...previous, ...page.items] : page.items);
      setNextCursor(page.next_cursor);
      setStatus('ready');
      setLoadingMore(false);
    }).catch((reason: unknown) => {
      if (ticket !== seq.current) return;
      setLoadingMore(false);
      if (append) {
        // 加载更多失败：保留原记录，重试沿用同一游标与过滤条件。
        setMoreError(`${describeApiError(reason, '加载更多失败')}；已加载记录保留，可按同一位置重试。`);
      } else {
        setRows([]);
        setNextCursor(null);
        setStatus('error');
        setError(reason instanceof ApiError && reason.status === 403
          ? '当前账号缺少资产或环境读取权限，请联系组织管理员。'
          : describeApiError(reason, '框架角色清单读取失败，不能据此判断没有框架实例。'));
      }
    });
  };

  const refresh = () => {
    seq.current += 1;
    usedCursors.current = new Set();
    setRows([]);
    setNextCursor(null);
    setMoreError('');
    setLoadingMore(false);
    loadPage(undefined, false);
  };

  const loadMore = () => {
    if (!nextCursor || loadingMore || status !== 'ready') return;
    loadPage(nextCursor, true);
  };

  const grouped = useMemo(() => groupFrameworkRoles(rows), [rows]);
  const hasUnknown = grouped.noRecordedSource.length > 0 || grouped.sourceUnavailable.length > 0;

  return <div className="framework-tree">
    <div className="row-actions">
      <button type="button" className="btn" disabled={status === 'loading'} onClick={refresh}>刷新框架实例视图</button>
    </div>
    {environmentId || deviceId
      ? <p className="framework-tree-note">当前请求保留已应用的{environmentId ? '环境' : ''}{environmentId && deviceId ? '与' : ''}{deviceId ? '设备' : ''}过滤。</p>
      : null}
    {status === 'loading' ? <p role="status">正在读取框架角色清单…</p> : null}
    {status === 'error' ? <p role="alert">{error} <button type="button" className="btn" onClick={refresh}>重试</button></p> : null}
    {status === 'ready' ? <>
      <p role="status">
        已加载 {rows.length} 条角色记录；仅为已加载页，不代表组织全量。
        {nextCursor ? '还有更多记录，可显式加载。' : '后端表示没有更多记录。'}
      </p>
      {grouped.conflictCount > 0
        ? <p role="alert">有 {grouped.conflictCount} 条资产记录在不同响应中内容不一致，显示不代表已核验，请刷新后核对。</p>
        : null}
      {rows.length === 0
        ? <p>本页没有角色资产记录。这不证明环境或设备中没有框架或角色，请核对接入状态与采集范围。</p>
        : null}
      {grouped.environments.map(environment =>
        <EnvironmentDisclosure key={environment.environmentId} environment={environment} />)}
      {hasUnknown ? <section className="framework-tree-pending" aria-label="来源待确认">
        <h2>来源待确认</h2>
        <p className="framework-tree-note">以下角色无法核验框架配置实例来源，不按名称或目录猜测归属。</p>
        <UnknownSourceSection title="无来源记录" roles={grouped.noRecordedSource}
          note="尚无框架来源记录，不代表未安装框架或没有角色。" />
        <UnknownSourceSection title="来源暂不可确认" roles={grouped.sourceUnavailable}
          note="来源记录存在异常或证据不完整，不能按名称猜测实例归属。" />
      </section> : null}
      {nextCursor ? <div className="list-more">
        <button type="button" className="btn" disabled={loadingMore} onClick={loadMore}>
          {loadingMore ? '正在加载…' : '加载更多角色记录'}
        </button>
      </div> : null}
      {moreError ? <p role="alert">{moreError} <button type="button" className="btn" disabled={loadingMore} onClick={loadMore}>按同一位置重试</button></p> : null}
    </> : null}
  </div>;
}

export default function FrameworkTreeView({ environmentId = '', deviceId = '' }: { environmentId?: string; deviceId?: string }) {
  const { data, status } = useConsoleContext();
  if (status === 'loading') return <p role="status">正在核对身份与权限，尚未读取框架角色清单…</p>;
  if (status === 'error' || !data) return <p role="alert">无法核对身份与权限，未读取框架角色清单。</p>;
  if (!data.access.agents || !data.access.environments) {
    return <p>当前账号缺少资产或环境读取权限，无法查看框架实例视图。请联系组织管理员申请。</p>;
  }
  // 身份（租户/操作者）或已应用过滤变化时整体重挂载，旧响应不得覆盖新结果。
  return <FrameworkTreeResults
    key={JSON.stringify([data.tenant.id, data.actor.type, data.actor.id, environmentId, deviceId])}
    environmentId={environmentId}
    deviceId={deviceId}
  />;
}
