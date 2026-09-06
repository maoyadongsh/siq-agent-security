/** DEV13-D：解析控制面列表分页响应头。本页条数不得冒充全量。 */

export const HDR_LIMIT = 'x-siq-list-limit';
export const HDR_RETURNED = 'x-siq-list-returned';
export const HDR_TRUNCATED = 'x-siq-list-truncated';
export const HDR_NEXT_CURSOR = 'x-siq-next-cursor';
export const HDR_TOTAL = 'x-siq-list-total';

export interface ListMeta {
  limit: number | null;
  returned: number | null;
  /** true=还有后续页；缺失头时视为未知（不得宣称「共 returned 条」） */
  truncated: boolean | null;
  nextCursor: string | null;
  total: number | null;
}

function parseIntHeader(headers: Headers, name: string): number | null {
  const raw = headers.get(name);
  if (raw == null || raw === '') return null;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) ? n : null;
}

export function parseListMeta(headers: Headers): ListMeta {
  const truncRaw = headers.get(HDR_TRUNCATED);
  let truncated: boolean | null = null;
  if (truncRaw === '1') truncated = true;
  else if (truncRaw === '0') truncated = false;

  return {
    limit: parseIntHeader(headers, HDR_LIMIT),
    returned: parseIntHeader(headers, HDR_RETURNED),
    truncated,
    nextCursor: headers.get(HDR_NEXT_CURSOR),
    total: parseIntHeader(headers, HDR_TOTAL),
  };
}

/** 用户可见摘要：明确区分「本页」与「总量」。 */
export function formatListCoverage(meta: ListMeta, shown: number): string {
  const page = meta.returned ?? shown;
  if (meta.total != null) {
    if (meta.truncated) {
      return `已显示 ${shown} 条（本页 ${page}），共 ${meta.total} 条；还有更多`;
    }
    return `已显示 ${shown} 条，共 ${meta.total} 条`;
  }
  if (meta.truncated === true) {
    return `已显示 ${shown} 条（本页 ${page}）；列表已截断，条数不是全量`;
  }
  if (meta.truncated === false) {
    return `已显示 ${shown} 条（本页完整，未截断）`;
  }
  return `已显示 ${shown} 条（未提供分页元数据，不得视为全量）`;
}
