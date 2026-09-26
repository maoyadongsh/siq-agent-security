/**
 * ENT-018-BINDINGS-UI：运行时绑定列表纯函数（筛选、安全枚举、选项状态、竞态）。
 * 只操作已加载记录；不发起请求、不写业务、不展开 attestation 原始字典。
 * 后端字符串一律按纯文本处理；未知枚举查表用 Object.hasOwn，
 * 避免 __proto__/constructor/toString 等原型属性名被继承出标签或样式。
 */
import type { AgentInstance, RuntimeBindingRow } from '@/api/types';

/* ---------------- 筛选 ---------------- */

export interface BindingFilters {
  /** '' = 全部；'active' | 'revoked' */
  status: string;
  /** '' = 全部；后端类型（从已加载数据推导） */
  backend: string;
  /** '' = 全部；环境（以实际 environment_id 为值，不猜测名称） */
  environment: string;
  /** 文本搜索：绑定 ID / 资产 ID / 实例 ID / 运行时目标 ID */
  query: string;
}

export const EMPTY_BINDING_FILTERS: BindingFilters = {
  status: '',
  backend: '',
  environment: '',
  query: '',
};

export function hasActiveBindingFilters(f: BindingFilters): boolean {
  return f.status !== '' || f.backend !== '' || f.environment !== '' || f.query.trim() !== '';
}

/** 从已加载记录推导后端类型（去重、排序）；不新增请求。 */
export function listBindingBackends(rows: readonly RuntimeBindingRow[]): string[] {
  const seen = new Set<string>();
  for (const r of rows) {
    if (typeof r.backend === 'string' && r.backend !== '') seen.add(r.backend);
  }
  return [...seen].sort();
}

/** 从已加载记录推导环境（以 environment_id 为值，不猜测名称）。 */
export function listBindingEnvironments(rows: readonly RuntimeBindingRow[]): string[] {
  const seen = new Set<string>();
  for (const r of rows) {
    if (typeof r.environment_id === 'string' && r.environment_id !== '') seen.add(r.environment_id);
  }
  return [...seen].sort();
}

/**
 * AND 组合筛选，仅作用于已加载记录。
 * 不同环境/实例/目标的同名记录不合并（逐条独立判断）。
 */
export function filterBindings(
  rows: readonly RuntimeBindingRow[],
  f: BindingFilters,
): RuntimeBindingRow[] {
  const q = f.query.trim().toLowerCase();
  return rows.filter((r) => {
    if (f.status !== '' && r.status !== f.status) return false;
    if (f.backend !== '' && r.backend !== f.backend) return false;
    if (f.environment !== '' && r.environment_id !== f.environment) return false;
    if (q !== '') {
      const haystack = [r.id, r.asset_id, r.agent_instance_id, r.backend_target_id]
        .map((v) => (typeof v === 'string' ? v.toLowerCase() : ''));
      if (!haystack.some((v) => v.includes(q))) return false;
    }
    return true;
  });
}

/* ---------------- 安全枚举展示 ---------------- */

const STATUS_TAG_CLASS: Record<string, string> = {
  active: 'tag-ok',
  revoked: 'tag-err',
};

/** 状态标签类：未知状态返回空串（保留原文，不冒充 active/revoked 或终态）。 */
export function statusTagClass(status: string): string {
  return Object.hasOwn(STATUS_TAG_CLASS, status) ? STATUS_TAG_CLASS[status] : '';
}

/** 缺失/空字段显示「未提供」；不展开 attestation。 */
export function textOrMissing(value: string | null | undefined): string {
  return value == null || value === '' ? '未提供' : value;
}

/* ---------------- 选项状态（环境/资产/实例） ---------------- */

export type OptionStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface OptionState<T> {
  status: OptionStatus;
  items: T[];
  error: string | null;
}

export const IDLE_OPTION: OptionState<never> = { status: 'idle', items: [], error: null };

/** 当前选择是否确实属于本次成功返回的选项（status 必须为 ready）。 */
export function optionHasId<T extends { id: string }>(state: OptionState<T>, id: string): boolean {
  return state.status === 'ready' && id !== '' && state.items.some((i) => i.id === id);
}

/* ---------------- 实例请求竞态（纯模型） ---------------- */

export interface InstanceRequestState {
  /** 请求序号：切换资产/清空/关闭/卸载时递增，使旧响应失效 */
  seq: number;
  /** 本次实例请求对应的资产 ID（null = 未选资产） */
  agentId: string | null;
  status: OptionStatus;
  items: AgentInstance[];
  error: string | null;
}

export const IDLE_INSTANCE_STATE: InstanceRequestState = {
  seq: 0,
  agentId: null,
  status: 'idle',
  items: [],
  error: null,
};

/** 切换/选定资产：递增序号、清空旧实例、进入加载。 */
export function beginInstanceRequest(state: InstanceRequestState, agentId: string): InstanceRequestState {
  return { seq: state.seq + 1, agentId, status: 'loading', items: [], error: null };
}

/** 清空资产/关闭表单/卸载：递增序号使在途响应失效，回到空闲。 */
export function invalidateInstanceRequest(state: InstanceRequestState): InstanceRequestState {
  return { seq: state.seq + 1, agentId: null, status: 'idle', items: [], error: null };
}

/**
 * 应用实例响应：仅当响应序号与当前序号一致（即当前资产）时更新。
 * 旧资产的成功/失败响应一律忽略，不覆盖当前状态。
 */
export function applyInstanceResponse(
  state: InstanceRequestState,
  responseSeq: number,
  ok: boolean,
  items: AgentInstance[],
  error: string | null,
): InstanceRequestState {
  if (responseSeq !== state.seq) return state;
  if (ok) return { ...state, status: 'ready', items, error: null };
  return { ...state, status: 'error', items: [], error };
}

/** 当前实例选择是否属于当前所选资产的这次成功结果。 */
export function instanceBelongsToCurrentAgent(
  state: InstanceRequestState,
  agentId: string,
  instanceId: string,
): boolean {
  return (
    state.status === 'ready' &&
    state.agentId === agentId &&
    agentId !== '' &&
    instanceId !== '' &&
    state.items.some((i) => i.id === instanceId)
  );
}
