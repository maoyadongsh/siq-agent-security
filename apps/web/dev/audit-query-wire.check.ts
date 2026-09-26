// ENT-019-AUDIT-WIRE：真实后端响应样本的消费者契约检查（独立 Vitest 配置运行）。
//
// 与 dev/*-wire.check.ts 的差别：本检查不 mock 客户端模块，而是走真实产品代码
// getListPage（src/api/client.ts：buildUrl 查询编码 + 信封/错误处理）与
// parseListMeta（src/api/listMeta.ts），仅在 fetch 层原样回放后端隔离测试导出的
// 状态码 / body / 列表元数据响应头。样本由 app/tests/test_audit_query_wire.py
// 经 SIQ_AUDIT_QUERY_WIRE_OUTPUT 指定路径导出（isolated-testclient-synthetic-data）。
//
// 证明范围：前后端对查询编码、分页与错误语义的契约兼容；不证明真实 IAM、
// 网关、PostgreSQL 或部署环境已验收。全过程无真实网络请求。

import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getListPage } from '../src/api/client';
import type { AuditEvent } from '../src/api/types';

const samplePath = process.env.SIQ_AUDIT_QUERY_WIRE_OUTPUT;
if (!samplePath) {
  throw new Error('SIQ_AUDIT_QUERY_WIRE_OUTPUT must identify the fresh isolated producer artifact');
}
const wire = JSON.parse(readFileSync(samplePath, 'utf8')) as {
  scope: string;
  endpoint: string;
  scenarios: Record<string, WireScenario>;
};

interface WireResponse {
  status: number;
  headers: Record<string, string>;
  body: unknown;
}

interface WireScenario {
  query: Record<string, string>;
  expected_ids?: string[];
  response?: WireResponse;
  pages?: WireResponse[];
  limit?: number;
  total?: number;
}

/** 客户端允许发送的查询参数全集（过滤 + 分页协议；不含任何租户/身份覆盖项）。 */
const ALLOWED_QUERY_KEYS = [
  'request_id',
  'resource_id',
  'actor_id',
  'actor_type',
  'action',
  'resource_type',
  'decision',
  'cursor',
  'limit',
  'include_total',
];

interface CapturedCall {
  url: string;
  method: string;
}

let calls: CapturedCall[] = [];
let violations: string[] = [];
let pending: WireResponse[] = [];

/** 受控 fetch 拦截：仅允许 GET；按队列原样回放样本响应；禁止浏览器存储访问。 */
function stubFetch(responses: WireResponse[]): void {
  calls = [];
  violations = [];
  pending = [...responses];
  const storageGuard = new Proxy(
    {},
    { get: () => {
      throw new Error('禁止访问浏览器存储');
    } },
  );
  vi.stubGlobal('localStorage', storageGuard);
  vi.stubGlobal('sessionStorage', storageGuard);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown, init?: { method?: string }) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      calls.push({ url, method });
      if (method !== 'GET') {
        violations.push(`非 GET 请求: ${method} ${url}`);
        throw new Error(violations[violations.length - 1]);
      }
      const next = pending.shift();
      if (!next) {
        violations.push(`未预期请求: ${url}`);
        throw new Error(violations[violations.length - 1]);
      }
      return new Response(JSON.stringify(next.body), {
        status: next.status,
        headers: next.headers,
      });
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  calls = [];
  violations = [];
  pending = [];
});

/** 解码后逐字核对期望参数，并拒绝任何白名单外的参数（租户覆盖 / 注入）。 */
function expectExactQuery(url: string, expected: Record<string, string>): void {
  const params = new URL(url).searchParams;
  for (const [key, value] of Object.entries(expected)) {
    expect(params.get(key)).toBe(value);
  }
  for (const key of params.keys()) {
    expect(ALLOWED_QUERY_KEYS).toContain(key);
  }
  expect(params.has('tenant_id')).toBe(false);
  expect(params.has('tenant')).toBe(false);
}

function expectCleanTransport(): void {
  expect(violations).toEqual([]);
  expect(calls.every((call) => call.method === 'GET')).toBe(true);
}

async function expectHttpError(scenario: WireScenario, status: number): Promise<void> {
  if (!scenario.response) throw new Error('样本缺少响应');
  stubFetch([scenario.response]);
  const error = await getListPage<AuditEvent>('/audit-events', { query: scenario.query }).then(
    () => null,
    (err: unknown) => err,
  );
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).status).toBe(status);
  expectCleanTransport();
}

describe('audit query wire sample（isolated-testclient-synthetic-data）', () => {
  it('样本来自隔离合成生产者且场景齐全', () => {
    expect(wire.scope).toBe('isolated-testclient-synthetic-data');
    expect(wire.endpoint).toBe('/api/v1/audit-events');
    for (const name of [
      'and_combo',
      'paged',
      'no_match',
      'tenant_a_shared',
      'tenant_b_shared',
      'forbidden',
      'unknown_values',
      'special_chars',
      'empty_request_id',
      'empty_resource_id',
      'empty_actor_type',
      'empty_decision',
      'overlong_request_id',
      'overlong_resource_id',
      'overlong_actor_type',
      'overlong_decision',
    ]) {
      expect(wire.scenarios[name], `缺少场景 ${name}`).toBeDefined();
    }
  });

  it('and_combo：新旧七个过滤条件逐字编码，真实响应可读且总数为 1', async () => {
    const scenario = wire.scenarios.and_combo;
    if (!scenario.response || !scenario.expected_ids) throw new Error('样本不完整');
    stubFetch([scenario.response]);
    const { items, meta } = await getListPage<AuditEvent>('/audit-events', {
      query: { ...scenario.query, limit: 50, include_total: true },
    });
    expect(items.map((row) => row.id)).toEqual(scenario.expected_ids);
    expect(meta.total).toBe(1);
    expect(meta.truncated).toBe(false);
    expect(calls).toHaveLength(1);
    // 解码后与输入逐字一致；limit/include_total 按产品协议合并进同一 query。
    expectExactQuery(calls[0].url, { ...scenario.query, limit: '50', include_total: 'true' });
    expectCleanTransport();
  });

  it('paged：翻页携带全部已应用条件，四页合并顺序符合夹具，总数不随翻页递减', async () => {
    const scenario = wire.scenarios.paged;
    if (!scenario.pages || !scenario.expected_ids || !scenario.limit || !scenario.total) {
      throw new Error('样本不完整');
    }
    stubFetch(scenario.pages);
    const ids: string[] = [];
    const totals: (number | null)[] = [];
    let cursor: string | undefined;
    for (let page = 0; page < scenario.pages.length; page += 1) {
      const { items, meta } = await getListPage<AuditEvent>('/audit-events', {
        query: { ...scenario.query, limit: scenario.limit, cursor, include_total: true },
      });
      ids.push(...items.map((row) => row.id));
      totals.push(meta.total);
      // 消费者协议：下一页 cursor 来自本次解析到的响应头，而非样本重放值。
      cursor = meta.nextCursor ?? undefined;
    }
    expect(scenario.pages.length).toBeGreaterThanOrEqual(3);
    // 合并后的 ID 集合与顺序 = 后端夹具预期（(created_at desc, id asc)）。
    expect(ids).toEqual(scenario.expected_ids);
    expect(new Set(ids).size).toBe(ids.length);
    expect(totals).toEqual(scenario.pages.map(() => scenario.total));
    calls.forEach((call, index) => {
      expectExactQuery(call.url, {
        ...scenario.query,
        limit: String(scenario.limit),
        include_total: 'true',
      });
      const params = new URL(call.url).searchParams;
      if (index === 0) {
        expect(params.has('cursor')).toBe(false);
      } else {
        // 翻页 cursor 与上一页真实响应头逐字一致。
        const previous = scenario.pages?.[index - 1];
        expect(params.get('cursor')).toBe(previous?.headers['x-siq-next-cursor']);
      }
    });
    expectCleanTransport();
  });

  it('no_match：空数组且 total=0 是明确值而非缺失', async () => {
    const scenario = wire.scenarios.no_match;
    if (!scenario.response) throw new Error('样本缺少响应');
    stubFetch([scenario.response]);
    const { items, meta } = await getListPage<AuditEvent>('/audit-events', {
      query: { ...scenario.query, limit: 50, include_total: true },
    });
    expect(items).toEqual([]);
    expect(meta.total).toBe(0);
    expect(meta.truncated).toBe(false);
    expectCleanTransport();
  });

  it('tenant_a_shared / tenant_b_shared：同名标识各自只读到本租户记录', async () => {
    for (const name of ['tenant_a_shared', 'tenant_b_shared']) {
      const scenario = wire.scenarios[name];
      if (!scenario.response || !scenario.expected_ids) throw new Error('样本不完整');
      stubFetch([scenario.response]);
      const { items, meta } = await getListPage<AuditEvent>('/audit-events', {
        query: { ...scenario.query, limit: 50, include_total: true },
      });
      expect(items.map((row) => row.id)).toEqual(scenario.expected_ids);
      expect(meta.total).toBe(1);
      expectExactQuery(calls[0].url, { ...scenario.query, limit: '50', include_total: 'true' });
      expectCleanTransport();
    }
    const aIds = wire.scenarios.tenant_a_shared.expected_ids ?? [];
    const bIds = wire.scenarios.tenant_b_shared.expected_ids ?? [];
    expect(aIds).not.toEqual(bIds);
  });

  it('forbidden：403 保留为错误，不伪装成成功空列表', async () => {
    await expectHttpError(wire.scenarios.forbidden, 403);
  });

  it('empty_*：新参数空字符串的 422 保留为错误', async () => {
    for (const name of ['empty_request_id', 'empty_resource_id', 'empty_actor_type', 'empty_decision']) {
      await expectHttpError(wire.scenarios[name], 422);
    }
  });

  it('overlong_*：新参数超长的 422 保留为错误', async () => {
    for (const name of [
      'overlong_request_id',
      'overlong_resource_id',
      'overlong_actor_type',
      'overlong_decision',
    ]) {
      await expectHttpError(wire.scenarios[name], 422);
    }
  });

  it('unknown_values：未知 actor_type/decision 原值通过，不改写为已知枚举或结论', async () => {
    const scenario = wire.scenarios.unknown_values;
    if (!scenario.response || !scenario.expected_ids) throw new Error('样本不完整');
    stubFetch([scenario.response]);
    const { items } = await getListPage<AuditEvent>('/audit-events', {
      query: { ...scenario.query, limit: 50, include_total: true },
    });
    expect(items.map((row) => row.id)).toEqual(scenario.expected_ids);
    // 客户端不得改写后端原值（包括改成 allow/deny 或推断性结论）。
    expect(items).toEqual(scenario.response.body);
    expect(items[0]?.actor_type).toBe('automaton-x');
    expect(items[0]?.decision).toBe('quarantine');
    expectExactQuery(calls[0].url, { ...scenario.query, limit: '50', include_total: 'true' });
    expectCleanTransport();
  });

  it('special_chars：空格/&/+/引号/中文与尾随空格编码往返逐字一致，不产生额外参数', async () => {
    const scenario = wire.scenarios.special_chars;
    if (!scenario.response || !scenario.expected_ids) throw new Error('样本不完整');
    stubFetch([scenario.response]);
    const { items } = await getListPage<AuditEvent>('/audit-events', {
      query: { ...scenario.query, limit: 50, include_total: true },
    });
    const raw = scenario.query.request_id;
    expect(raw).toMatch(/[&+"'\s]/);
    expect(raw).toMatch(/加/);
    expect(raw).not.toBe(raw.trim());
    expect(items.map((row) => row.id)).toEqual(scenario.expected_ids);
    // 解码后逐字等于原值（含尾随空格），响应值不被 trim / 改大小写。
    expect(new URL(calls[0].url).searchParams.get('request_id')).toBe(raw);
    expect(items[0]?.request_id).toBe(raw);
    expectExactQuery(calls[0].url, { ...scenario.query, limit: '50', include_total: 'true' });
    expectCleanTransport();
  });

  it('结束后恢复 fetch 与浏览器存储替身', () => {
    expect(vi.isMockFunction(globalThis.fetch)).toBe(false);
    expect(violations).toEqual([]);
  });
});
