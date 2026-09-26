/** FrameworkTreeView 行为测试（ENT-018-FRAMEWORK-TREE-UI）。
 * vitest 为 node 环境且本任务不安装依赖（无 jsdom/testing-library），
 * 复用 RuntimeBindingsPage 的最小 DOM shim + react-dom/client 做真实渲染行为测试；
 * 键盘/视口/溢出由隔离浏览器测试（framework-tree-browser-smoke.py）覆盖。
 *
 * 注意：shim 模块必须在 react/react-dom 之前 import。 */
import { FakeElement, fakeDocument } from '@/pages/runtimeBindingPageDomShim';
import { describe, expect, it, vi } from 'vitest';

/* ---------------- 模块 mock（@/api/client 全量可控；真实解析器保留） ---------------- */
const { ApiError, getMock } = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
    }
  }
  return { ApiError, getMock: vi.fn() };
});

vi.mock('@/api/client', () => ({
  ApiError,
  describeApiError: (err: unknown, fallback = '操作失败') =>
    err instanceof Error ? err.message : fallback,
  get: (...args: unknown[]) => getMock(...args),
}));

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ConsoleContextProvider } from '@/components/ConsoleContext';
import FrameworkTreeView from './FrameworkTreeView';

/* ---------------- fixture 工厂 ---------------- */
const ALL_ACCESS = ['workspace', 'overview', 'agents', 'permissions', 'findings', 'policies',
  'changes', 'runtime_bindings', 'environments', 'audit', 'settings'];

function consoleContext(access: Record<string, boolean> = {}) {
  return {
    schema_version: 'console-context/v1', evaluated_at: '2026-09-25T00:00:00Z',
    tenant: { id: 'tenant-fixture', name: 'Fixture' }, actor: { id: 'user-fixture', type: 'user' },
    authentication: 'development_headers', roles: [], custom_role_count: 0,
    access: { ...Object.fromEntries(ALL_ACCESS.map(key => [key, true])), ...access },
    actions: Object.fromEntries(['confirm_assets', 'manage_environment', 'enroll_devices',
      'manage_policy', 'propose_change', 'approve_change'].map(key => [key, false])),
  };
}

const INSTANCE_KEY = 'a'.repeat(64);

function sourceView(assetId: string, overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 'enterprise-framework-source-view/v1', asset_id: assetId,
    status: 'historical_reported_source', runtime_status: 'unverified',
    skill_relationship_status: 'unresolved', effective_permissions: null,
    source: {
      framework: 'openclaw', instance_key: INSTANCE_KEY, environment_id: 'env-one',
      device_id: 'edge-one', device_revoked: false, config_sha256: 'b'.repeat(64),
      evidence_id: 'ev:one', observation_id: 'evo-one', observed_at: '2026-09-25T12:00:00Z',
    },
    ...overrides,
  };
}

function role(assetId: string, overrides: Record<string, unknown> = {}) {
  return {
    asset_id: assetId, name: `角色 ${assetId}`, reported_framework: 'openclaw',
    asset_status: 'confirmed', framework_source: sourceView(assetId), ...overrides,
  };
}

function page(items: unknown[], nextCursor: string | null = null) {
  return {
    schema_version: 'enterprise-framework-role-inventory/v1',
    coverage: 'page_of_tenant_assets', items, next_cursor: nextCursor,
  };
}

function defer<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

/** 首页 fixture：同实例两角色 + 一条无来源记录；下一页游标 agt_e。 */
function pageOne() {
  return page([
    role('agt_a', { name: 'web-scraper' }),
    role('agt_b', { name: 'web-scraper' }), // 同名角色不去重
    role('agt_e', { framework_source: sourceView('agt_e', { status: 'no_recorded_source', source: null }) }),
  ], 'agt_e');
}

/** 第二页 fixture：同实例第三角色（跨页合并）+ 不同设备相同 instance_key + 来源异常。 */
function pageTwo() {
  return page([
    role('agt_f'),
    role('agt_g', {
      framework_source: sourceView('agt_g', {
        source: { ...sourceView('agt_g').source, device_id: 'edge-two' },
      }),
    }),
    role('agt_h', { framework_source: sourceView('agt_h', { status: 'source_unavailable', source: null }) }),
  ]);
}

type Query = { environment_id?: string; device_id?: string; cursor?: string; limit?: number };

/** 按路径路由的可控 get：console-context + framework-role-inventory。 */
function routeGet(options: {
  context?: () => Promise<unknown>;
  inventory: (query: Query | undefined) => Promise<unknown>;
}) {
  getMock.mockReset(); // 测试体内重置（beforeEach 钩子重置会让后续 rejection 被误报，见 api 测试注释）
  getMock.mockImplementation((path: string, request?: { query?: Query }) => {
    if (path === '/console-context') return options.context ? options.context() : Promise.resolve(consoleContext());
    if (path === '/framework-role-inventory') return options.inventory(request?.query);
    return Promise.reject(new Error(`unexpected request: ${path}`));
  });
}

const inventoryCalls = () =>
  getMock.mock.calls.filter(([path]) => path === '/framework-role-inventory')
    .map(([, request]) => (request as { query?: Query } | undefined)?.query);

it('keeps provenance per role when the same instance has different configuration observations', async () => {
  routeGet({ inventory: async () => page([
    role('agt_a'), role('agt_b', { framework_source: sourceView('agt_b', {
      source: { ...sourceView('agt_b').source, config_sha256: 'c'.repeat(64), evidence_id: 'ev:second',
        observation_id: 'evo-second', observed_at: '2026-09-24T12:00:00Z' },
    }) }),
  ]) });
  const { container, root } = await renderView();
  try {
    const roles = container.querySelectorAll('.framework-tree-role');
    expect(roles).toHaveLength(2);
    expect(roles[0].innerHTML).toContain('ev:one');
    expect(roles[0].innerHTML).not.toContain('ev:second');
    expect(roles[1].innerHTML).toContain('ev:second');
    expect(roles[1].innerHTML).toContain('c'.repeat(64));
    expect(roles[1].innerHTML).toContain('2026-09-24T12:00:00Z');
  } finally {
    await act(async () => { root.unmount(); });
  }
});

async function renderView(props: { environmentId?: string; deviceId?: string } = {}) {
  const container = new FakeElement('div');
  container.ownerDocument = fakeDocument;
  const root: Root = createRoot(container as unknown as DocumentFragment);
  await act(async () => {
    root.render(<MemoryRouter><ConsoleContextProvider>
      <FrameworkTreeView {...props} />
    </ConsoleContextProvider></MemoryRouter>);
  });
  await act(async () => {});
  const click = (target: FakeElement) => {
    let defaultPrevented = false;
    const event = {
      type: 'click', target, currentTarget: container, nativeEvent: null,
      bubbles: true, cancelable: true,
      preventDefault() { defaultPrevented = true; },
      stopPropagation() {}, stopImmediatePropagation() {},
      isDefaultPrevented: () => defaultPrevented, isPropagationStopped: () => false, persist() {},
    };
    for (const fn of container.listeners.click ?? []) fn(event);
  };
  const button = (text: string) =>
    container.querySelectorAll('button').find(b => b.textContent?.includes(text)) ?? null;
  return { container, root, html: () => container.innerHTML, click, button };
}

/* ---------------- 身份与权限门禁 ---------------- */
describe('身份与权限门禁', () => {
  it('身份加载中：不发清单请求', async () => {
    routeGet({ context: () => defer().promise, inventory: () => defer().promise });
    const { html, root } = await renderView();
    expect(html()).toContain('正在核对身份与权限');
    expect(inventoryCalls()).toHaveLength(0);
    root.unmount();
  });

  it('身份失败：不发清单请求', async () => {
    routeGet({ context: () => Promise.reject(new ApiError(0, '无法连接')), inventory: () => defer().promise });
    const { html, root } = await renderView();
    await act(async () => {});
    expect(html()).toContain('无法核对身份与权限');
    expect(inventoryCalls()).toHaveLength(0);
    root.unmount();
  });

  it.each(['agents', 'environments'])('缺少 %s 权限：不发清单请求', async key => {
    routeGet({ context: () => Promise.resolve(consoleContext({ [key]: false })), inventory: () => defer().promise });
    const { html, root } = await renderView();
    await act(async () => {});
    expect(html()).toContain('缺少资产或环境读取权限');
    expect(inventoryCalls()).toHaveLength(0);
    root.unmount();
  });
});

/* ---------------- 渲染与分组 ---------------- */
describe('渲染与分组', () => {
  it('首页渲染 环境→设备→实例→角色 层级，同名角色不去重，未知来源单列', async () => {
    routeGet({ inventory: () => Promise.resolve(page([...pageOne().items, role('agt_i', { name: '<script>bad()</script>' })])) });
    const { container, html, root } = await renderView();
    await act(async () => {});
    const output = html();
    expect(output).toContain('环境');
    expect(output).toContain('env-one');
    expect(output).toContain('edge-one');
    expect(output).toContain(INSTANCE_KEY);
    expect(output).toContain('已加载 3 个角色（非完整清单）');
    expect(output.match(/web-scraper/g)).toHaveLength(2); // 同名不去重
    expect(output).toContain('来源待确认');
    expect(output).toContain('无来源记录');
    expect(output).toContain('不代表进程正在运行');
    expect(output).toContain('技能安装关系待确认');
    expect(output).toContain('不代表组织全量');
    // XSS 名称只作为文本，不产生 script 元素
    expect(output).toContain('<script>bad()</script>');
    expect(container.querySelectorAll('script')).toHaveLength(0);
    root.unmount();
  });

  it('每个角色提供 /agents/:id 详情链接', async () => {
    routeGet({ inventory: () => Promise.resolve(page([role('agt_a')])) });
    const { container, root } = await renderView();
    await act(async () => {});
    const link = container.querySelector('a');
    expect(link).not.toBeNull();
    expect(link!.attributes.href).toBe('/agents/agt_a?view=framework');
    root.unmount();
  });

  it('空页：明确空态，不冒充错误也不冒充有数据', async () => {
    routeGet({ inventory: () => Promise.resolve(page([])) });
    const { html, root } = await renderView();
    await act(async () => {});
    expect(html()).toContain('本页没有角色资产记录');
    expect(html()).not.toContain('读取失败');
    root.unmount();
  });

  it('首页失败：错误可重试，不显示为空列表', async () => {
    let fail = true;
    routeGet({
      inventory: () => fail
        ? Promise.reject(new ApiError(0, '无法连接控制面'))
        : Promise.resolve(page([role('agt_a')])),
    });
    const { html, root, click, button } = await renderView();
    await act(async () => {});
    expect(html()).toContain('无法连接控制面');
    expect(html()).not.toContain('本页没有角色资产记录');
    fail = false;
    await act(async () => { click(button('重试')!); });
    await act(async () => {});
    expect(html()).toContain('agt_a');
    root.unmount();
  });

  it('403 响应：权限提示而非空列表', async () => {
    routeGet({ inventory: () => Promise.reject(new ApiError(403, 'denied')) });
    const { html, root } = await renderView();
    await act(async () => {});
    expect(html()).toContain('缺少资产或环境读取权限');
    expect(html()).not.toContain('本页没有角色资产记录');
    root.unmount();
  });

  it('响应格式错误：明确失败，不当成空列表', async () => {
    routeGet({ inventory: () => Promise.resolve({ schema_version: 'other' }) });
    const { html, root } = await renderView();
    await act(async () => {});
    expect(html()).toContain('无法核验');
    expect(html()).not.toContain('本页没有角色资产记录');
    root.unmount();
  });

  it('请求保留已应用的 environment_id/device_id，且不携带身份覆盖参数', async () => {
    routeGet({ inventory: () => Promise.resolve(page([])) });
    const { root } = await renderView({ environmentId: 'env-nine', deviceId: 'edge-nine' });
    await act(async () => {});
    const calls = inventoryCalls();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({ environment_id: 'env-nine', device_id: 'edge-nine', cursor: undefined, limit: 50 });
    expect(JSON.stringify(calls[0])).not.toContain('tenant');
    root.unmount();
  });
});

/* ---------------- 分页、刷新与竞态 ---------------- */
describe('分页、刷新与竞态', () => {
  it('加载更多：同实例跨页合并，不同设备同 instance_key 不混并', async () => {
    routeGet({
      inventory: query => Promise.resolve(query?.cursor === 'agt_e' ? pageTwo() : pageOne()),
    });
    const { html, root, click, button } = await renderView();
    await act(async () => {});
    expect(html()).toContain('已加载 3 条角色记录');
    await act(async () => { click(button('加载更多')!); });
    await act(async () => {});
    const output = html();
    expect(output).toContain('已加载 6 条角色记录');
    // edge-one 实例合并为 3 个角色；edge-two 同 instance_key 独立成组
    expect(output).toContain('已加载 3 个角色（非完整清单）');
    expect(output).toContain('edge-two');
    expect(output).toContain('已加载 1 个角色（非完整清单）');
    // 未知来源两种状态分开展示
    expect(output).toContain('无来源记录');
    expect(output).toContain('来源暂不可确认');
    expect(output).toContain('后端表示没有更多记录');
    expect(inventoryCalls().map(q => q?.cursor)).toEqual([undefined, 'agt_e']);
    root.unmount();
  });

  it('加载更多失败：保留已加载记录，按同一游标重试成功', async () => {
    let failPageTwo = true;
    routeGet({
      inventory: query => {
        if (query?.cursor !== 'agt_e') return Promise.resolve(pageOne());
        return failPageTwo ? Promise.reject(new ApiError(0, '网络中断')) : Promise.resolve(pageTwo());
      },
    });
    const { html, root, click, button } = await renderView();
    await act(async () => {});
    await act(async () => { click(button('加载更多')!); });
    await act(async () => {});
    expect(html()).toContain('网络中断');
    expect(html()).toContain('agt_a'); // 原记录保留
    failPageTwo = false;
    await act(async () => { click(button('按同一位置重试')!); });
    await act(async () => {});
    expect(html()).toContain('已加载 6 条角色记录');
    // 两次翻页使用同一游标，不跳页
    expect(inventoryCalls().map(q => q?.cursor)).toEqual([undefined, 'agt_e', 'agt_e']);
    root.unmount();
  });

  it('重复点击加载更多不并发重复请求', async () => {
    const pending = defer<unknown>();
    routeGet({
      inventory: query => query?.cursor === 'agt_e' ? pending.promise : Promise.resolve(pageOne()),
    });
    const { root, click, button } = await renderView();
    await act(async () => {});
    await act(async () => { click(button('加载更多')!); });
    // 加载中按钮禁用，再点不会发出第二个请求
    expect(button('正在加载')).not.toBeNull();
    await act(async () => { click(button('正在加载')!); });
    expect(inventoryCalls()).toHaveLength(2);
    await act(async () => { pending.resolve(pageTwo()); });
    root.unmount();
  });

  it('刷新替换数据，不混合旧页与新页', async () => {
    let generation = 1;
    routeGet({
      inventory: () => Promise.resolve(generation === 1
        ? pageOne()
        : page([role('agt_z', { name: '刷新后角色' })])),
    });
    const { html, root, click, button } = await renderView();
    await act(async () => {});
    expect(html()).toContain('agt_a');
    generation = 2;
    await act(async () => { click(button('刷新框架实例视图')!); });
    await act(async () => {});
    const output = html();
    expect(output).toContain('刷新后角色');
    expect(output).not.toContain('agt_a');
    expect(output).toContain('已加载 1 条角色记录');
    root.unmount();
  });

  it('刷新后迟到的旧响应不得覆盖新结果', async () => {
    const stale = defer<unknown>();
    routeGet({
      inventory: query => {
        if (query?.cursor === 'agt_e') return stale.promise; // 旧「加载更多」迟迟不返回
        return Promise.resolve(page([role('agt_z', { name: '刷新后角色' })]));
      },
    });
    // 首轮需要首页为 pageOne：用计数区分第一次首页与刷新后的首页
    let firstPage = true;
    getMock.mockImplementation((path: string, request?: { query?: Query }) => {
      if (path === '/console-context') return Promise.resolve(consoleContext());
      if (path === '/framework-role-inventory') {
        const query = request?.query;
        if (query?.cursor === 'agt_e') return stale.promise;
        if (firstPage) { firstPage = false; return Promise.resolve(pageOne()); }
        return Promise.resolve(page([role('agt_z', { name: '刷新后角色' })]));
      }
      return Promise.reject(new Error(`unexpected request: ${path}`));
    });
    const { html, root, click, button } = await renderView();
    await act(async () => {});
    await act(async () => { click(button('加载更多')!); }); // 旧请求挂起
    await act(async () => { click(button('刷新框架实例视图')!); }); // 刷新完成新一轮
    await act(async () => {});
    expect(html()).toContain('刷新后角色');
    // 旧响应迟到
    await act(async () => { stale.resolve(pageTwo()); });
    await act(async () => {});
    const output = html();
    expect(output).toContain('刷新后角色');
    expect(output).not.toContain('角色 agt_f'); // pageTwo 的角色没有混入
    expect(output).toContain('已加载 1 条角色记录');
    root.unmount();
  });
});
