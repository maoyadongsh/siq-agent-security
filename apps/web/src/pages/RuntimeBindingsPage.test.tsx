/** RuntimeBindingsPage 行为测试（ENT-018-BINDINGS-UI）。
 * vitest 为 node 环境且本任务不安装依赖（无 jsdom/testing-library），
 * 故使用最小 DOM shim（runtimeBindingPageDomShim）+ react-dom/client 做真实渲染
 * 行为测试（非源码字符串匹配）；交互（键盘/视口/溢出）由隔离浏览器测试覆盖。
 * 关键覆盖：列表状态区分、表单选项状态、资产切换竞态（A→B 乱序）、创建/吊销载荷与失败语义。
 *
 * 注意：shim 模块必须在 react/react-dom 之前 import——react-dom 在模块加载期
 * 计算 canUseDOM 与 isInputEventSupported，shim 的 Proxy document 需先就位。 */
import { FakeElement, fakeDocument } from './runtimeBindingPageDomShim';
import { describe, expect, it, vi } from 'vitest';

/* ---------------- 模块 mock（@/api/client 全量可控） ---------------- */
const { ApiError, getListPageMock, listEnvironmentsMock, listAgentsMock, getAgentInstancesMock, createRuntimeBindingMock, revokeRuntimeBindingMock } = vi.hoisted(() => {
  class ApiError extends Error {
    status = 0;
    constructor(message: string) {
      super(message);
      this.name = 'ApiError';
    }
  }
  return {
    ApiError,
    getListPageMock: vi.fn(),
    listEnvironmentsMock: vi.fn(),
    listAgentsMock: vi.fn(),
    getAgentInstancesMock: vi.fn(),
    createRuntimeBindingMock: vi.fn(),
    revokeRuntimeBindingMock: vi.fn(),
  };
});

vi.mock('@/api/client', () => ({
  ApiError,
  describeApiError: (err: unknown, fallback = '操作失败') =>
    err instanceof Error ? err.message : fallback,
  getListPage: (...args: unknown[]) => getListPageMock(...args),
  api: {
    listEnvironments: (...args: unknown[]) => listEnvironmentsMock(...args),
    listAgents: (...args: unknown[]) => listAgentsMock(...args),
    getAgentInstances: (...args: unknown[]) => getAgentInstancesMock(...args),
    createRuntimeBinding: (...args: unknown[]) => createRuntimeBindingMock(...args),
    revokeRuntimeBinding: (...args: unknown[]) => revokeRuntimeBindingMock(...args),
  },
}));

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import RuntimeBindingsPage from './RuntimeBindingsPage';
import type { AgentAsset, AgentInstance, Environment, RuntimeBindingRow } from '@/api/types';

/* ---------------- fixture 工厂 ---------------- */
function env(id: string): Environment {
  return { id, tenant_id: 't1', name: `环境 ${id}`, env_type: 'host', mode: 'observe', risk_level: 'low', last_heartbeat_at: null };
}
function asset(id: string, status: AgentAsset['status'] = 'managed'): AgentAsset {
  return { id, name: `资产 ${id}`, role: null, framework: 'hermes', status, system_id: null, owner_user_id: null, source_type: null, source_locator: null, updated_at: '2026-09-01T00:00:00Z' };
}
function inst(id: string): AgentInstance {
  return { id, runtime: 'hermes', version: null, artifact_digest: null, location: {}, status: 'running', observed_at: null };
}
function bindingRow(overrides: Partial<RuntimeBindingRow> = {}): RuntimeBindingRow {
  return {
    id: 'rb-1', tenant_id: 't1', environment_id: 'env-1', agent_instance_id: 'inst-1',
    asset_id: 'agt-1', backend: 'openshell-cli', backend_target_id: 'target-1',
    attestation: {}, status: 'active', created_at: '2026-09-01T00:00:00Z', revoked_at: null,
    ...overrides,
  };
}

function defer<T>(_initial?: T) {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** 默认：列表成功返回 1 条 active 绑定；环境/资产成功；实例按需。 */
function setupDefaults() {
  getListPageMock.mockResolvedValue({ items: [bindingRow()], meta: { limit: 50, returned: 1, truncated: false, nextCursor: null, total: null } });
  listEnvironmentsMock.mockResolvedValue([env('env-1')]);
  listAgentsMock.mockResolvedValue([asset('agt-1'), asset('agt-2', 'candidate')]);
  createRuntimeBindingMock.mockResolvedValue(bindingRow());
  revokeRuntimeBindingMock.mockResolvedValue(bindingRow({ status: 'revoked' }));
}

async function render() {
  const container = new FakeElement('div');
  container.ownerDocument = fakeDocument;
  const root: Root = createRoot(container as unknown as DocumentFragment);
  await act(async () => {
    root.render(<RuntimeBindingsPage />);
  });
  const click = (target: FakeElement) => {
    let defaultPrevented = false;
    const event = {
      type: 'click', target, currentTarget: container, nativeEvent: null,
      bubbles: true, cancelable: true,
      preventDefault() { defaultPrevented = true; },
      stopPropagation() {}, stopImmediatePropagation() {},
      isDefaultPrevented: () => defaultPrevented, isPropagationStopped: () => false, persist() {},
    };
    // 门户（ConfirmDialog → document.body）的委托监听在 body 上，主容器在 container 上
    for (const fn of container.listeners.click ?? []) fn(event);
    for (const fn of (fakeDocument.body as FakeElement).listeners.click ?? []) fn(event);
  };
  const change = (target: FakeElement, value: string) => {
    target.value = value;
    let defaultPrevented = false;
    const event = {
      type: 'change', target, currentTarget: container, nativeEvent: null,
      bubbles: true, cancelable: true,
      preventDefault() { defaultPrevented = true; },
      stopPropagation() {}, stopImmediatePropagation() {},
      isDefaultPrevented: () => defaultPrevented, isPropagationStopped: () => false, persist() {},
    };
    for (const fn of container.listeners.change ?? []) fn(event);
  };
  return { container, root, html: () => container.innerHTML, click, change };
}

/** 找到 form-box 内第 n 个 select（0=环境,1=资产,2=实例）。 */
function selects(container: FakeElement): FakeElement[] {
  const formBox = container.querySelector('.form-box');
  return formBox ? formBox.querySelectorAll('select') : [];
}
/** 找到 form-box 内的「登记」按钮。 */
function createButton(container: FakeElement): FakeElement | null {
  const formBox = container.querySelector('.form-box');
  if (!formBox) return null;
  const btns = formBox.querySelectorAll('button');
  return btns.find((b) => b.textContent?.includes('登记') && !b.textContent?.includes('登记绑定')) ?? null;
}

describe('列表状态区分', () => {
  it('首次加载显示加载提示，不显示「暂无绑定」或伪零', async () => {
    getListPageMock.mockReturnValue(defer().promise);
    const { html, root } = await render();
    expect(html()).toContain('正在加载运行时绑定');
    expect(html()).not.toContain('暂无');
    root.unmount();
  });

  it('成功空列表：明确「后端成功返回空列表」', async () => {
    getListPageMock.mockResolvedValue({ items: [], meta: { limit: 50, returned: 0, truncated: false, nextCursor: null, total: null } });
    const { html, root } = await render();
    await act(async () => {});
    expect(html()).toContain('后端成功返回空列表');
    expect(html()).toContain('已加载 0 条');
    root.unmount();
  });

  it('首次失败：错误与重试，不冒充空列表', async () => {
    getListPageMock.mockRejectedValue(Object.assign(new Error('boom'), { name: 'ApiError' }));
    const { html, root } = await render();
    await act(async () => {});
    expect(html()).toContain('未连接');
    expect(html()).toContain('重试连接');
    expect(html()).not.toContain('后端成功返回空列表');
    root.unmount();
  });

  it('筛选无匹配：提示清除筛选', async () => {
    setupDefaults();
    const { container, html, root, change } = await render();
    await act(async () => {});
    // 输入搜索词使无匹配
    const search = container.querySelector('.rb-explorer-field-search input') as FakeElement;
    await act(async () => {
      change(search, '不存在的ID');
    });
    expect(html()).toContain('当前筛选条件下无匹配项');
    expect(html()).toContain('清除筛选');
    root.unmount();
  });
});

describe('登记表单选项状态', () => {
  it('打开表单才加载环境/资产（按需）', async () => {
    setupDefaults();
    const { container, root, click } = await render();
    await act(async () => {});
    expect(listEnvironmentsMock).not.toHaveBeenCalled();
    expect(listAgentsMock).not.toHaveBeenCalled();
    // 点击「登记绑定」
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => {
      click(toolbar);
    });
    await act(async () => {});
    expect(listEnvironmentsMock).toHaveBeenCalledTimes(1);
    expect(listAgentsMock).toHaveBeenCalledTimes(1);
    root.unmount();
  });

  it('环境加载失败：明确报错+重试，不以空列表替代', async () => {
    setupDefaults();
    listEnvironmentsMock.mockRejectedValue(Object.assign(new Error('环境服务故障'), { name: 'ApiError' }));
    const { container, html, root, click } = await render();
    await act(async () => {});
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => { click(toolbar); });
    await act(async () => {});
    expect(html()).toContain('环境加载失败');
    expect(html()).toContain('环境服务故障');
    expect(html()).toContain('重试');
    root.unmount();
  });

  it('选项加载中时不能创建（登记按钮禁用）', async () => {
    setupDefaults();
    listEnvironmentsMock.mockReturnValue(defer().promise); // 永不返回
    const { container, root, click } = await render();
    await act(async () => {});
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => { click(toolbar); });
    await act(async () => {});
    const btn = createButton(container);
    expect(btn).not.toBeNull();
    expect(btn!.attributes.disabled).toBeDefined();
    root.unmount();
  });

  it('选择不匹配已加载选项时不能创建', async () => {
    setupDefaults();
    const { container, html, root, click } = await render();
    await act(async () => {});
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => { click(toolbar); });
    await act(async () => {});
    // 未选环境/资产/实例 → 登记按钮禁用（环境/资产已成功加载，首个未通过项为实例）
    const btn = createButton(container);
    expect(btn!.attributes.disabled).toBeDefined();
    expect(html()).toContain('实例选项尚未成功加载');
    root.unmount();
  });
});

describe('资产切换竞态', () => {
  it('A 未完成时切换 B：B 先返回、A 后返回，最终仍是 B', async () => {
    setupDefaults();
    const aDeferred = defer<AgentInstance[]>([inst('inst-A1')]);
    const bDeferred = defer<AgentInstance[]>([inst('inst-B1')]);
    getAgentInstancesMock
      .mockImplementationOnce(() => aDeferred.promise)
      .mockImplementationOnce(() => bDeferred.promise);
    const { container, html, root, click, change } = await render();
    await act(async () => {});
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => { click(toolbar); });
    await act(async () => {});
    // 选资产 A
    const sel = selects(container);
    await act(async () => { change(sel[1], 'agt-1'); });
    await act(async () => {});
    // 立即切换到资产 B（A 的实例请求尚未返回）
    await act(async () => { change(sel[1], 'agt-2'); });
    await act(async () => {});
    // B 先返回
    await act(async () => { bDeferred.resolve([inst('inst-B1')]); });
    await act(async () => {});
    // A 后返回（旧请求）→ 应被忽略
    await act(async () => { aDeferred.resolve([inst('inst-A1')]); });
    await act(async () => {});
    // 实例下拉应显示 B 的实例，而非 A 的
    const instanceHtml = html();
    expect(instanceHtml).toContain('inst-B1');
    expect(instanceHtml).not.toContain('inst-A1');
    root.unmount();
  });

  it('A 旧请求失败不覆盖 B 成功', async () => {
    setupDefaults();
    const aDeferred = defer<AgentInstance[]>([]);
    const bDeferred = defer<AgentInstance[]>([inst('inst-B1')]);
    getAgentInstancesMock
      .mockImplementationOnce(() => aDeferred.promise)
      .mockImplementationOnce(() => bDeferred.promise);
    const { container, html, root, click, change } = await render();
    await act(async () => {});
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => { click(toolbar); });
    await act(async () => {});
    const sel = selects(container);
    await act(async () => { change(sel[1], 'agt-1'); });
    await act(async () => { change(sel[1], 'agt-2'); });
    await act(async () => { bDeferred.resolve([inst('inst-B1')]); });
    await act(async () => {});
    // A 失败（旧请求）→ 忽略
    await act(async () => { aDeferred.reject(Object.assign(new Error('A 故障'), { name: 'ApiError' })); });
    await act(async () => {});
    expect(html()).toContain('inst-B1');
    expect(html()).not.toContain('A 故障');
    root.unmount();
  });

  it('清空资产后旧实例结果失效', async () => {
    setupDefaults();
    const aDeferred = defer<AgentInstance[]>([inst('inst-A1')]);
    getAgentInstancesMock.mockImplementationOnce(() => aDeferred.promise);
    const { container, html, root, click, change } = await render();
    await act(async () => {});
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => { click(toolbar); });
    await act(async () => {});
    const sel = selects(container);
    await act(async () => { change(sel[1], 'agt-1'); });
    // 清空资产（选回空）
    await act(async () => { change(sel[1], ''); });
    // A 的迟到成功响应 → 应被忽略
    await act(async () => { aDeferred.resolve([inst('inst-A1')]); });
    await act(async () => {});
    expect(html()).not.toContain('inst-A1');
    root.unmount();
  });
});

describe('登记/吊销载荷与失败语义', () => {
  it('未知绑定状态不冒充终态，且不提供吊销操作', async () => {
    setupDefaults();
    // 模拟线协议新增/异常枚举；不扩大生产类型允许的登记状态。
    getListPageMock.mockResolvedValue({ items: [{ ...bindingRow(), status: 'pending-verification' }], meta: { limit: 50, returned: 1, truncated: false, nextCursor: null, total: null } });
    const { container, html, root } = await render();
    try {
      expect(html()).toContain('pending-verification');
      expect(html()).not.toContain('已终态');
      expect(container.querySelector('.rb-explorer-actions button')).toBeNull();
    } finally {
      await act(async () => { root.unmount(); });
    }
  });

  it('登记在途锁定输入及收起操作，失败后解锁并保留原始输入', async () => {
    setupDefaults();
    getAgentInstancesMock.mockResolvedValue([inst('inst-1')]);
    const pending = defer<RuntimeBindingRow>();
    createRuntimeBindingMock.mockReturnValue(pending.promise);
    const { container, html, root, click, change } = await render();
    try {
      const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
      await act(async () => { click(toolbar); });
      await act(async () => { change(selects(container)[0], 'env-1'); });
      await act(async () => { change(selects(container)[1], 'agt-1'); });
      await act(async () => { change(selects(container)[2], 'inst-1'); });
      const target = container.querySelector('.form-box')!.querySelectorAll('input')[1];
      await act(async () => { change(target, 'original-target'); });
      await act(async () => { click(createButton(container)!); });
      expect(toolbar.attributes.disabled).toBeDefined();
      for (const input of container.querySelector('.form-box')!.querySelectorAll('input')) {
        expect(input.attributes.disabled).toBeDefined();
      }
      for (const select of selects(container)) expect(select.attributes.disabled).toBeDefined();
      await act(async () => { pending.reject(new ApiError('模拟失败')); });
      expect(toolbar.attributes.disabled).toBeUndefined();
      expect(target.attributes.disabled).toBeUndefined();
      expect(target.value).toBe('original-target');
      expect(html()).toContain('模拟失败');
    } finally {
      await act(async () => { root.unmount(); });
    }
  });

  it('登记成功：正确载荷、关闭表单、刷新列表', async () => {
    setupDefaults();
    getAgentInstancesMock.mockResolvedValue([inst('inst-1')]);
    const { container, root, click, change } = await render();
    await act(async () => {});
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => { click(toolbar); });
    await act(async () => {});
    const sel = selects(container);
    await act(async () => { change(sel[0], 'env-1'); });
    await act(async () => { change(sel[1], 'agt-1'); });
    await act(async () => {});
    // 实例加载完成后选择
    const sel2 = selects(container);
    await act(async () => { change(sel2[2], 'inst-1'); });
    // 填后端目标
    const inputs = container.querySelector('.form-box')!.querySelectorAll('input');
    await act(async () => {
      change(inputs[1] as FakeElement, 'sandbox-01');
    });
    const btn = createButton(container);
    expect(btn!.attributes.disabled).toBeUndefined();
    await act(async () => { click(btn!); });
    await act(async () => {});
    expect(createRuntimeBindingMock).toHaveBeenCalledWith({
      environment_id: 'env-1',
      agent_instance_id: 'inst-1',
      backend: 'openshell-cli',
      backend_target_id: 'sandbox-01',
    });
    root.unmount();
  });

  it('登记失败：保留输入、明确报错', async () => {
    setupDefaults();
    getAgentInstancesMock.mockResolvedValue([inst('inst-1')]);
    createRuntimeBindingMock.mockRejectedValue(new ApiError('后端拒绝'));
    const { container, html, root, click, change } = await render();
    await act(async () => {});
    const toolbar = container.querySelector('.permissions-toolbar button') as FakeElement;
    await act(async () => { click(toolbar); });
    await act(async () => {});
    const sel = selects(container);
    await act(async () => { change(sel[0], 'env-1'); });
    await act(async () => { change(sel[1], 'agt-1'); });
    await act(async () => {});
    const sel2 = selects(container);
    await act(async () => { change(sel2[2], 'inst-1'); });
    const inputs = container.querySelector('.form-box')!.querySelectorAll('input');
    await act(async () => {
      change(inputs[1] as FakeElement, 'sandbox-01');
    });
    const btn = createButton(container);
    await act(async () => { click(btn!); });
    await act(async () => {});
    expect(html()).toContain('后端拒绝');
    root.unmount();
  });

  it('吊销：正确载荷（reason 固定）', async () => {
    setupDefaults();
    const { container, root, click } = await render();
    await act(async () => {});
    // 点击 active 行的吊销按钮
    const revokeBtn = container.querySelector('.rb-explorer-actions button') as FakeElement;
    await act(async () => { click(revokeBtn); });
    await act(async () => {});
    // 确认弹窗中的确认按钮
    const confirmBtn = (fakeDocument.body as FakeElement).querySelectorAll('button').find((b) => b.textContent?.includes('确认吊销')) as FakeElement;
    await act(async () => { click(confirmBtn); });
    await act(async () => {});
    expect(revokeRuntimeBindingMock).toHaveBeenCalledWith('rb-1', 'web-console-manual-revoke');
    root.unmount();
  });
});
