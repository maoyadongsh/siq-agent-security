/**
 * ENT-019-AUDIT-SEARCH-UI：审计精确查询的纯函数层。
 *
 * 语义边界（packages/contracts/enterprise-audit-query.v1 + models.py AuditEvent 字段长度）：
 * - 全部为精确相等匹配；多个条件同时满足（AND），查询服务端审计记录而非已加载列表；
 * - 空字符串省略参数（不发送 request_id= 等空值）；非空值不 trim、不转小写、不截断；
 * - 超过字段上限返回可读校验错误，调用方不得发送请求；
 * - actor_type / decision 不限定为当前已知枚举，合法长度内的未知原值也允许查询；
 * - 本模块不引入 tenant、身份或权限覆盖参数。
 */

/** 七个可查询字段；request_id / resource_id 为主查询，其余进入“更多查询条件”。 */
export interface AuditSearchFilters {
  request_id: string;
  resource_id: string;
  actor_id: string;
  actor_type: string;
  action: string;
  resource_type: string;
  decision: string;
}

export const EMPTY_AUDIT_FILTERS: AuditSearchFilters = {
  request_id: '',
  resource_id: '',
  actor_id: '',
  actor_type: '',
  action: '',
  resource_type: '',
  decision: '',
};

export interface AuditFilterFieldSpec {
  key: keyof AuditSearchFilters;
  /** 展示用中文名（同时用于校验提示与已应用条件描述） */
  label: string;
  /** 最大长度：合同 v1（新参数）与 models.py AuditEvent 字段（旧参数） */
  max: number;
}

/** 主查询字段（表单默认可见） */
export const AUDIT_PRIMARY_FIELDS: readonly AuditFilterFieldSpec[] = [
  { key: 'request_id', label: '请求编号', max: 64 },
  { key: 'resource_id', label: '对象编号', max: 64 },
];

/** 更多查询条件（默认折叠） */
export const AUDIT_ADVANCED_FIELDS: readonly AuditFilterFieldSpec[] = [
  { key: 'actor_id', label: '操作者编号', max: 64 },
  { key: 'actor_type', label: '操作者类型', max: 16 },
  { key: 'action', label: '动作', max: 64 },
  { key: 'resource_type', label: '对象类型', max: 32 },
  { key: 'decision', label: '决策原值', max: 16 },
];

export const AUDIT_FILTER_FIELDS: readonly AuditFilterFieldSpec[] = [
  ...AUDIT_PRIMARY_FIELDS,
  ...AUDIT_ADVANCED_FIELDS,
];

export type AuditFilterErrors = Partial<Record<keyof AuditSearchFilters, string>>;

/** 与后端 Query(max_length=…) 同口径：按 Unicode 码点数计长（Python len 语义）。 */
export function codePointLength(value: string): number {
  return [...value].length;
}

/**
 * 校验全部七个字段的长度上限。返回字段 → 可读错误信息；空串不参与校验（将被省略）。
 * 只做长度校验：不改变值、不限制枚举、不拒绝特殊字符（它们只是精确匹配的数据）。
 */
export function validateAuditFilters(filters: AuditSearchFilters): AuditFilterErrors {
  const errors: AuditFilterErrors = {};
  for (const { key, label, max } of AUDIT_FILTER_FIELDS) {
    const value = filters[key];
    if (value === '') continue;
    const length = codePointLength(value);
    if (length > max) {
      errors[key] = `${label}长度 ${length} 超过上限 ${max}：请缩短后再查询（未发送请求）`;
    }
  }
  return errors;
}

export function hasAuditFilterErrors(errors: AuditFilterErrors): boolean {
  return Object.values(errors).some(Boolean);
}

/** 是否有任一非空条件（空串 = 未填写，不 trim）。 */
export function hasActiveAuditFilters(filters: AuditSearchFilters): boolean {
  return AUDIT_FILTER_FIELDS.some(({ key }) => filters[key] !== '');
}

export function auditFiltersEqual(a: AuditSearchFilters, b: AuditSearchFilters): boolean {
  return AUDIT_FILTER_FIELDS.every(({ key }) => a[key] === b[key]);
}

/**
 * 构造服务端查询参数：空串省略，非空原值保留（不 trim / 不转小写 / 不截断）。
 * 返回的 Record 供 getListPage 的 query 选项使用，由客户端 buildUrl 经
 * URL.searchParams 统一编码并与 cursor / limit / include_total 合并，
 * 调用方不得手工拼接查询字符串。
 */
export function buildAuditQuery(filters: AuditSearchFilters): Record<string, string> {
  const query: Record<string, string> = {};
  for (const { key } of AUDIT_FILTER_FIELDS) {
    const value = filters[key];
    if (value !== '') query[key] = value;
  }
  return query;
}

/** 已应用条件的人类可读片段，如「请求编号 = req-1」。 */
export function describeAppliedFilters(filters: AuditSearchFilters): string[] {
  const parts: string[] = [];
  for (const { key, label } of AUDIT_FILTER_FIELDS) {
    const value = filters[key];
    if (value !== '') parts.push(`${label} = ${value}`);
  }
  return parts;
}

/**
 * 结果组件 key 的查询部分：固定字段顺序的 JSON 元组序列化，保证相同条件得到相同 key
 * （相同条件重复提交不触发重新请求；条件变化即更换 key，旧结果组件卸载）。
 *
 * CL-06-AUDIT-CORRELATION-UI：旧实现用未转义的 `key=value` + `&` 拼接，
 * 值中的 `&`/`=` 可制造跨字段碰撞（如 request_id="a&resource_id=b" + resource_id="c"
 * 与 request_id="a" + resource_id="b&resource_id=c" 生成同一 key），
 * 使已应用条件变化后旧结果组件不卸载、旧查询结果滞留。
 * JSON.stringify 对字符串做完整转义，元组内每个值边界明确，无歧义。
 */
export function auditFiltersKey(filters: AuditSearchFilters): string {
  return JSON.stringify(AUDIT_FILTER_FIELDS.map(({ key }) => filters[key]));
}

/**
 * 身份元组（租户 + 操作者类型 + 操作者）的无歧义序列化，用于查询会话隔离。
 * 不再用 `#`/`|`/`&` 拼接（值含分隔符时不同身份可碰撞）；
 * 只序列化两个 ID 和身份类型，令牌或完整身份响应不进入 key。
 */
export function identityKey(tenantId: string, actorId: string, actorType: string = ''): string {
  return JSON.stringify([tenantId, actorType, actorId]);
}
