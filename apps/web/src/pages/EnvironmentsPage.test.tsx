/** EnvironmentsPage 行为测试（CL-02-ENVIRONMENT-LIST-CLOSEOUT）。
 * vitest 为 node 环境且本任务不安装依赖，故使用最小 DOM shim + react-dom/client
 * 做真实渲染行为测试（非源码字符串匹配）；交互（键盘/视口）由隔离浏览器测试覆盖。
 * API 全部经 mock 合成，不访问真实控制面。 */
import { describe, expect, it, vi, beforeAll, afterAll, beforeEach } from 'vitest';

/* ---------------- 最小 DOM shim（仅覆盖 React 18 渲染所需） ---------------- */
class FakeElement {
  nodeType = 1;
  tagName: string;
  parentNode: FakeElement | null = null;
  childNodes: FakeElement[] = [];
  attributes: Record<string, string> = {};
  listeners: Record<string, ((e?: unknown) => void)[]> = {};
  style: Record<string, string> = {};
  options: FakeElement[] = [];
  ownerDocument: unknown = null;
  constructor(tag: string) {
    this.tagName = tag.toUpperCase();
  }
  // React ChangeEventPlugin/isTextInputElement 依赖 nodeName 与 input.type 判定 onChange 派发
  get nodeName() {
    return this.tagName;
  }
  get type() {
    return this.tagName === 'INPUT' ? this.attributes.type ?? 'text' : '';
  }
  get textContent() {
    return (this._text ?? '') + this.childNodes.map((c) => c.textContent ?? '').join('');
  }
  set textContent(v: string) {
    this.childNodes = [];
    this._text = v;
  }
  protected _text = '';
  /* 受控 input/select 语义：React 的值追踪包装 node 实例属性，
   * 模拟原生 setter 需经 prototype 访问器绕过（见 input 助手）。 */
  get value() {
    return this._domValue;
  }
  set value(v: string) {
    this._domValue = String(v);
  }
  private _domValue = '';
  get nodeValue() {
    return this._text;
  }
  set nodeValue(v: string) {
    this._text = v;
  }
  get firstChild() {
    return this.childNodes[0] ?? null;
  }
  appendChild(node: FakeElement) {
    this.insertBefore(node, null);
    return node;
  }
  insertBefore(node: FakeElement, ref: FakeElement | null) {
    if (node.parentNode) node.parentNode.removeChild(node);
    const at = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
    this.childNodes.splice(at < 0 ? this.childNodes.length : at, 0, node);
    node.parentNode = this;
    return node;
  }
  removeChild(node: FakeElement) {
    const at = this.childNodes.indexOf(node);
    if (at >= 0) this.childNodes.splice(at, 1);
    node.parentNode = null;
    return node;
  }
  setAttribute(name: string, value: string) {
    this.attributes[name] = String(value);
  }
  removeAttribute(name: string) {
    delete this.attributes[name];
  }
  getAttribute(name: string) {
    return this.attributes[name] ?? null;
  }
  hasAttribute(name: string) {
    return name in this.attributes;
  }
  addEventListener(type: string, fn: (e?: unknown) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  removeEventListener(type: string, fn: (e?: unknown) => void) {
    this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn);
  }
  focus() {}
  blur() {}
  querySelector(sel: string): FakeElement | null {
    return this.querySelectorAll(sel)[0] ?? null;
  }
  querySelectorAll(sel: string): FakeElement[] {
    const out: FakeElement[] = [];
    const match = (el: FakeElement): boolean => {
      if (sel.startsWith('.')) return el.attributes.class?.split(' ').includes(sel.slice(1)) ?? false;
      const role = sel.match(/^\[role=(\w+)\]$/);
      if (role) return el.attributes.role === role[1];
      return false;
    };
    const walk = (el: FakeElement) => {
      for (const child of el.childNodes) {
        if (child.nodeType !== 1) continue;
        if (match(child)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
  get innerHTML() {
    const render = (el: FakeElement): string => {
      const attrs = Object.entries(el.attributes)
        .map(([k, v]) => ` ${k}="${v}"`)
        .join('');
      const own = el._text ?? '';
      return `<${el.tagName.toLowerCase()}${attrs}>${own}${el.childNodes.map(render).join('')}</${el.tagName.toLowerCase()}>`;
    };
    return this.childNodes.map(render).join('');
  }
}
class FakeText extends FakeElement {
  nodeType = 3;
  constructor(text: string) {
    super('#text');
    this._text = text;
  }
}
const fakeDocument = {
  nodeType: 9,
  createElement: (tag: string) => new FakeElement(tag),
  createElementNS: (_ns: string, tag: string) => new FakeElement(tag),
  createTextNode: (text: string) => new FakeText(text),
  createComment: (text: string) => new FakeText(text),
  body: new FakeElement('body'),
  head: new FakeElement('head'),
  documentElement: new FakeElement('html'),
  activeElement: null as FakeElement | null,
  // React 的 isEventSupported('input') 检查 'oninput' in document；
  // 缺失会退回 IE9 polyfill 路径，导致受控 input 的 onChange 永不派发。
  oninput: null,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
};
class FakeNode {}
class FakeText2 extends FakeNode {}
class FakeComment extends FakeNode {}
class FakeElement2 extends FakeNode {}
class FakeHTMLElement extends FakeElement2 {}
class FakeHTMLIFrameElement extends FakeHTMLElement {}
/* react-dom 在模块加载时计算 canUseDOM/isInputEventSupported，
 * 必须在 document/window 全局就位后再导入。 */
let createRoot: typeof import('react-dom/client').createRoot;
beforeAll(async () => {
  (globalThis as Record<string, unknown>).document = fakeDocument;
  const win = {
    addEventListener: () => {},
    removeEventListener: () => {},
    location: { origin: 'http://127.0.0.1', href: 'http://127.0.0.1/' },
    Node: FakeNode,
    Text: FakeText2,
    Comment: FakeComment,
    Element: FakeElement2,
    HTMLElement: FakeHTMLElement,
    HTMLIFrameElement: FakeHTMLIFrameElement,
    getSelection: () => null,
    document: fakeDocument,
  };
  (globalThis as Record<string, unknown>).window = win;
  (globalThis as Record<string, unknown>).Node = FakeNode;
  (globalThis as Record<string, unknown>).HTMLElement = FakeHTMLElement;
  (globalThis as Record<string, unknown>).HTMLIFrameElement = FakeHTMLIFrameElement;
  (globalThis as Record<string, unknown>).Text = FakeText2;
  (globalThis as Record<string, unknown>).Comment = FakeComment;
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  ({ createRoot } = await import('react-dom/client'));
  ({ MemoryRouter } = await import('react-router-dom'));
  ({ default: EnvironmentsPage } = await import('./EnvironmentsPage'));
});
afterAll(() => {
  delete (globalThis as Record<string, unknown>).document;
  delete (globalThis as Record<string, unknown>).window;
  delete (globalThis as Record<string, unknown>).Node;
  delete (globalThis as Record<string, unknown>).HTMLElement;
  delete (globalThis as Record<string, unknown>).HTMLIFrameElement;
  delete (globalThis as Record<string, unknown>).Text;
  delete (globalThis as Record<string, unknown>).Comment;
  delete (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT;
});

/* ---------------- 模块 mock ---------------- */
const listPage = vi.fn();
vi.mock('@/api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
      this.name = 'ApiError';
    }
  },
  describeApiError: (err: unknown, fallback = '操作失败') => (err instanceof Error ? err.message : fallback),
  getListPage: (...args: unknown[]) => listPage(...args),
}));
const accessMock = vi.fn();
const createMock = vi.fn();
vi.mock('@/api/onboarding', () => ({
  onboardingApi: {
    access: (...args: unknown[]) => accessMock(...args),
    create: (...args: unknown[]) => createMock(...args),
  },
}));
vi.mock('@/components/onboarding/EnvironmentSetup', () => ({
  default: (props: { environment: { id: string } }) => <div>{`[接入引导面板:${props.environment.id}]`}</div>,
}));
vi.mock('@/components/onboarding/InstallPlanSetup', () => ({
  default: (props: { environment: string }) => <div>{`[安装计划面板:${props.environment}]`}</div>,
}));
vi.mock('@/components/onboarding/EnterpriseConnectionPanel', () => ({
  default: (props: { environmentId: string }) => <div>{`[企业连接面板:${props.environmentId}]`}</div>,
}));
vi.mock('@/components/device-lifecycle/DeviceLifecyclePanel', () => ({
  default: (props: { environmentId: string }) => <div>{`[设备生命周期面板:${props.environmentId}]`}</div>,
}));
vi.mock('@/components/discovery-schedule-management/DiscoverySchedulePanel', () => ({
  default: (props: { environmentId: string }) => <div>{`[周期计划面板:${props.environmentId}]`}</div>,
}));

import { act } from 'react';
import type { Root } from 'react-dom/client';
/* react-router-dom 入口静态引 react-dom（见 beforeAll 注释），须延迟动态导入 */
let MemoryRouter: typeof import('react-router-dom').MemoryRouter;
let EnvironmentsPage: (typeof import('./EnvironmentsPage'))['default'];
import type { Environment } from '@/api/types';
import type { ListMeta } from '@/api/listMeta';

beforeEach(() => { listPage.mockClear(); accessMock.mockClear(); createMock.mockClear(); });

/* ---------------- 夹具 ---------------- */
const env = (n: number): Environment => ({
  id: `env-${String(n).padStart(2, '0')}`,
  tenant_id: 't-fixture',
  name: `环境-${n}`,
  env_type: 'host',
  mode: 'discovery',
  risk_level: 'low',
  last_heartbeat_at: null,
});
const envs = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => env(from + i));
const meta = (overrides: Partial<ListMeta> = {}): ListMeta => ({
  limit: 50, returned: null, truncated: null, nextCursor: null, total: null, ...overrides,
});
const FULL_ACCESS = { schema_version: 'environment-onboarding-access/v1' as const, can_create: true, can_enroll: true, can_scan: true, can_view_assets: true };

interface Query { limit?: number; cursor?: string; include_total?: boolean }
const cursors = () => listPage.mock.calls.map((call) => (call[1] as { query?: Query } | undefined)?.query?.cursor);

/* ---------------- 渲染与交互 ---------------- */
async function render(initial = '/environments', access: unknown = FULL_ACCESS) {
  if (access instanceof Error) accessMock.mockRejectedValue(access);
  else accessMock.mockResolvedValue(access);
  const container = new FakeElement('div');
  container.ownerDocument = fakeDocument;
  const root: Root = createRoot(container as unknown as DocumentFragment);
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[initial]}>
        <EnvironmentsPage />
      </MemoryRouter>,
    );
  });
  await act(async () => {});
  const fire = (type: string, target: FakeElement) => {
    const event = {
      type, target, currentTarget: container, nativeEvent: null, bubbles: true, cancelable: true,
      preventDefault() {}, stopPropagation() {}, stopImmediatePropagation() {},
      isDefaultPrevented: () => false, isPropagationStopped: () => false, persist() {},
    };
    // React 在根容器为同一事件注册多个优先级监听器；只触发第一个，
    // 避免一次用户操作被插件系统重复处理。
    const fns = container.listeners[type] ?? [];
    if (fns.length) fns[0](event);
  };
  const button = (text: string) =>
    container.querySelectorAll('.btn').find((b) => b.textContent === text) ?? null;
  const nativeValue = Object.getOwnPropertyDescriptor(FakeElement.prototype, 'value');
  const input = async (element: FakeElement, value: string) => {
    nativeValue?.set?.call(element, value);
    await act(async () => { fire('input', element); });
  };
  return { container, root, html: () => container.innerHTML, fire, button, input,
    alerts: () => container.querySelectorAll('[role=alert]') as FakeElement[],
    statuses: () => container.querySelectorAll('[role=status]') as FakeElement[] };
}


describe('分页接入（复现首批截断不可达）', () => {
  it('复现：服务端首批返回 50 条并声明 next_cursor 时，可通过显式按钮加载第 51 条并选择', async () => {
    listPage.mockImplementation(async (_path: string, options?: { query?: Query }) => {
      if (!options?.query?.cursor) {
        return { items: envs(1, 50), meta: meta({ returned: 50, truncated: true, nextCursor: 'cursor-page-2', total: 77 }) };
      }
      expect(options.query.cursor).toBe('cursor-page-2');
      return { items: envs(51, 51), meta: meta({ returned: 1, truncated: false, nextCursor: null, total: 77 }) };
    });
    const { container, html, root, fire, button } = await render();
    expect(html()).toContain('环境-50');
    expect(html()).not.toContain('环境-51');
    expect(html()).toContain('已显示 50 条');
    expect(html()).toContain('共 77 条');
    const more = button('加载更多环境');
    expect(more).not.toBeNull();
    await act(async () => { fire('click', more as FakeElement); });
    expect(html()).toContain('环境-51');
    expect(cursors()).toEqual([undefined, 'cursor-page-2']);
    expect(button('加载更多环境')).toBeNull();
    // 第 51 条出现在桌面与移动两个列表中，取最后一个按钮（env-51 行）选择它
    const rowButtons = container.querySelectorAll('.btn').filter((b) => b.textContent === '查看接入进度');
    expect(rowButtons.length).toBe(51 * 2);
    await act(async () => { fire('click', rowButtons[rowButtons.length - 1]); });
    expect(html()).toContain('[接入引导面板:env-51]');
    expect(html()).toContain('[安装计划面板:env-51]');
    root.unmount();
  });

  it('加载更多期间按钮禁用、文案明确且不重复发送同一分页请求', async () => {
    let resolveMore!: (value: unknown) => void;
    listPage.mockImplementation(async (_path: string, options?: { query?: Query }) => {
      if (!options?.query?.cursor) return { items: envs(1, 50), meta: meta({ returned: 50, truncated: true, nextCursor: 'cursor-page-2' }) };
      return new Promise((resolve) => { resolveMore = resolve; });
    });
    const { html, root, fire, button } = await render();
    const more = button('加载更多环境') as FakeElement;
    await act(async () => { fire('click', more); });
    expect(button('正在加载更多环境…')).not.toBeNull();
    expect(listPage.mock.calls.length).toBe(2);
    await act(async () => { fire('click', more); });
    expect(listPage.mock.calls.length).toBe(2);
    await act(async () => { resolveMore({ items: envs(51, 55), meta: meta({ returned: 5, truncated: false }) }); });
    expect(html()).toContain('环境-55');
    expect(button('加载更多环境')).toBeNull();
    root.unmount();
  });

  it('分页失败保留已加载记录与选择，同游标重试成功并清除错误', async () => {
    listPage.mockImplementation(async (_path: string, options?: { query?: Query }) => {
      if (!options?.query?.cursor) return { items: envs(1, 50), meta: meta({ returned: 50, truncated: true, nextCursor: 'cursor-page-2' }) };
      if (options.query.cursor === 'cursor-page-2' && listPage.mock.calls.length === 2) throw new Error('请求失败（503）');
      return { items: envs(51, 51), meta: meta({ returned: 1, truncated: false }) };
    });
    const { html, root, fire, button, alerts } = await render('/environments?environment=env-51');
    await act(async () => { fire('click', button('加载更多环境') as FakeElement); });
    expect(alerts().length).toBe(1);
    expect(html()).toContain('请求失败（503）');
    expect(html()).toContain('环境-50');
    expect(html()).not.toContain('环境-51');
    expect(button('加载更多环境')).not.toBeNull();
    expect(cursors()).toEqual([undefined, 'cursor-page-2']);
    await act(async () => { fire('click', button('加载更多环境') as FakeElement); });
    expect(alerts().length).toBe(0);
    expect(html()).toContain('环境-51');
    expect(html()).toContain('[接入引导面板:env-51]');
    expect(cursors()).toEqual([undefined, 'cursor-page-2', 'cursor-page-2']);
    root.unmount();
  });

  it('刷新从第一页重读，晚到的旧分页响应不混入结果', async () => {
    let resolveStaleAppend!: (value: unknown) => void;
    listPage.mockImplementation(async (_path: string, options?: { query?: Query }) => {
      if (!options?.query?.cursor) {
        if (listPage.mock.calls.length === 1) return { items: envs(1, 50), meta: meta({ returned: 50, truncated: true, nextCursor: 'cursor-page-2' }) };
        return { items: envs(1, 50), meta: meta({ returned: 50, truncated: false, total: 50 }) };
      }
      return new Promise((resolve) => { resolveStaleAppend = resolve; });
    });
    const { html, root, fire, button } = await render();
    await act(async () => { fire('click', button('加载更多环境') as FakeElement); });
    await act(async () => { fire('click', button('刷新环境列表') as FakeElement); });
    await act(async () => { resolveStaleAppend({ items: envs(51, 60), meta: meta({ returned: 10, truncated: false }) }); });
    expect(html()).not.toContain('环境-51');
    expect(html()).toContain('环境-50');
    expect(html()).toContain('已显示 50 条，共 50 条');
    expect(button('加载更多环境')).toBeNull();
    expect(cursors()).toEqual([undefined, 'cursor-page-2', undefined]);
    root.unmount();
  });
});

describe('清单覆盖范围如实展示', () => {
  it('刷新在途时不能用旧游标加载更多抢占刷新', async () => {
    let finishRefresh!: (value: unknown) => void;
    listPage.mockImplementation(async () => {
      if (listPage.mock.calls.length === 1) return { items: envs(1, 50), meta: meta({ returned: 50, truncated: true, nextCursor: 'old-cursor' }) };
      return new Promise(resolve => { finishRefresh = resolve; });
    });
    const { root, fire, button } = await render();
    await act(async () => { fire('click', button('刷新环境列表') as FakeElement); });
    await act(async () => { fire('click', button('加载更多环境') as FakeElement); });
    expect(listPage.mock.calls.length).toBe(2);
    await act(async () => { finishRefresh({ items: envs(1, 2), meta: meta({ returned: 2, truncated: false }) }); });
    root.unmount();
  });
  it('total=0 与「尚无环境」仅在服务端声明完整时出现', async () => {
    listPage.mockResolvedValue({ items: [], meta: meta({ returned: 0, truncated: false, total: 0 }) });
    const { html, root } = await render();
    expect(html()).toContain('已显示 0 条，共 0 条');
    expect(html()).toContain('尚无环境，请先创建。');
    root.unmount();
  });

  it('分页元数据缺失时不冒充全量、不宣称 0', async () => {
    listPage.mockResolvedValue({ items: [], meta: meta({ limit: null, returned: null, truncated: null }) });
    const { html, root } = await render();
    expect(html()).toContain('未提供分页元数据，不得视为全量');
    expect(html()).not.toContain('尚无环境，请先创建。');
    expect(html()).not.toContain('共 0 条');
    root.unmount();
  });

  it('截断且缺 total 时说明清单不完整，且仍可加载更多', async () => {
    listPage.mockImplementation(async (_path: string, options?: { query?: Query }) => {
      if (!options?.query?.cursor) return { items: envs(1, 2), meta: meta({ returned: 2, truncated: true, nextCursor: 'c2' }) };
      return { items: [env(3)], meta: meta({ returned: 1, truncated: false }) };
    });
    const { html, root, fire, button } = await render();
    expect(html()).toContain('列表已截断，条数不是全量');
    expect(html()).not.toContain('共');
    expect(button('加载更多环境')).not.toBeNull();
    await act(async () => { fire('click', button('加载更多环境') as FakeElement); });
    expect(html()).toContain('环境-3');
    expect(html()).toContain('已显示 3 条（本页完整，未截断）');
    root.unmount();
  });
});

describe('URL 选择与交互安全', () => {
  it('URL 环境未加载且有下一页时提示可继续加载，不误判不存在、不挂载面板、不自动切换', async () => {
    listPage.mockImplementation(async (_path: string, options?: { query?: Query }) => {
      if (!options?.query?.cursor) return { items: envs(1, 50), meta: meta({ returned: 50, truncated: true, nextCursor: 'cursor-page-2' }) };
      return { items: [env(77)], meta: meta({ returned: 1, truncated: false }) };
    });
    const { html, root, fire, button } = await render('/environments?environment=env-77');
    expect(html()).toContain('在当前已加载记录中尚未找到');
    expect(html()).toContain('加载更多');
    expect(html()).not.toContain('[接入引导面板:');
    expect(html()).not.toContain('[安装计划面板:');
    expect(html()).not.toContain('[设备生命周期面板:');
    expect(html()).not.toContain('[周期计划面板:');
    expect(html()).not.toContain('[接入引导面板:env-01]');
    await act(async () => { fire('click', button('加载更多环境') as FakeElement); });
    expect(html()).toContain('[接入引导面板:env-77]');
    expect(html()).toContain('[安装计划面板:env-77]');
    expect(html()).toContain('[设备生命周期面板:env-77]');
    expect(html()).toContain('[周期计划面板:env-77]');
    expect(html()).not.toContain('尚未找到');
    root.unmount();
  });

  it('URL 环境在完整清单中未找到时只说明可见列表未找到', async () => {
    listPage.mockResolvedValue({ items: envs(1, 2), meta: meta({ returned: 2, truncated: false, total: 2 }) });
    const { html, root } = await render('/environments?environment=env-77');
    expect(html()).toContain('当前可见列表中未找到');
    expect(html()).not.toContain('尚未找到');
    expect(html()).not.toContain('[接入引导面板:');
    expect(html()).not.toContain('已删除');
    expect(html()).not.toContain('没有权限');
    root.unmount();
  });

  it('加载更多不改变 URL 选择，已选环境在追加后保持挂载', async () => {
    listPage.mockImplementation(async (_path: string, options?: { query?: Query }) => {
      if (!options?.query?.cursor) return { items: envs(1, 50), meta: meta({ returned: 50, truncated: true, nextCursor: 'cursor-page-2' }) };
      return { items: envs(51, 55), meta: meta({ returned: 5, truncated: false }) };
    });
    const { html, root, fire, button } = await render('/environments?environment=env-03');
    expect(html()).toContain('[接入引导面板:env-03]');
    await act(async () => { fire('click', button('加载更多环境') as FakeElement); });
    expect(html()).toContain('[接入引导面板:env-03]');
    expect(html()).toContain('环境-55');
    root.unmount();
  });
});

describe('创建语义保留', () => {
  it('创建载荷不变；未知结果不自动重发，仅显式重试', async () => {
    listPage.mockResolvedValue({ items: [env(1)], meta: meta({ returned: 1, truncated: false, total: 1 }) });
    createMock.mockRejectedValueOnce(new Error('网络中断，结果未知'));
    const { html, root, fire, input, container } = await render();
    const form = findByTag(container, 'form');
    expect(form).not.toBeNull();
    const nameInput = findByTag(form as FakeElement, 'input');
    await input(nameInput as FakeElement, '新环境');
    await act(async () => { fire('submit', form as FakeElement); });
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(createMock).toHaveBeenCalledWith('新环境', 'host');
    expect(html()).toContain('未确认创建结果');
    await act(async () => {});
    expect(createMock).toHaveBeenCalledTimes(1);
    createMock.mockResolvedValueOnce({ id: 'env-new', tenant_id: 't', name: '新环境', env_type: 'host', mode: 'discovery', risk_level: 'low', last_heartbeat_at: null });
    await act(async () => { fire('submit', form as FakeElement); });
    expect(createMock).toHaveBeenCalledTimes(2);
    root.unmount();
  });

  it('同名 409 提示保持原语义，不自动改写或重复提交', async () => {
    listPage.mockResolvedValue({ items: [], meta: meta({ returned: 0, truncated: false, total: 0 }) });
    const { ApiError } = await import('@/api/client');
    createMock.mockRejectedValue(new ApiError(409, '同名环境已存在'));
    const { html, root, fire, input, container } = await render();
    const form = findByTag(container, 'form');
    const nameInput = findByTag(form as FakeElement, 'input') as FakeElement;
    await input(nameInput, '重复名');
    await act(async () => { fire('submit', form as FakeElement); });
    expect(createMock).toHaveBeenCalledTimes(1);
    expect(html()).toContain('同名环境已存在，请刷新列表并选择该环境继续。');
    await act(async () => {});
    expect(createMock).toHaveBeenCalledTimes(1);
    root.unmount();
  });
});

describe('权限门禁保留', () => {
  it('无创建/注册权限时不出现对应入口，选中环境仍可查看', async () => {
    listPage.mockResolvedValue({ items: [env(1)], meta: meta({ returned: 1, truncated: false, total: 1 }) });
    accessMock.mockResolvedValue({ ...FULL_ACCESS, can_create: false, can_enroll: false });
    const { html, root } = await render('/environments?environment=env-01', { ...FULL_ACCESS, can_create: false, can_enroll: false });
    expect(html()).not.toContain('创建环境并接入');
    expect(html()).toContain('[接入引导面板:env-01]');
    expect(html()).not.toContain('[安装计划面板:');
    expect(html()).toContain('[企业连接面板:env-01]');
    root.unmount();
  });

  it('接入权限读取失败时显示错误，不出现创建表单或环境面板', async () => {
    listPage.mockResolvedValue({ items: [env(1)], meta: meta({ returned: 1, truncated: false, total: 1 }) });
    accessMock.mockRejectedValue(new Error('权限服务不可用'));
    const { html, root } = await render('/environments?environment=env-01', new Error('权限服务不可用'));
    expect(html()).toContain('无法读取接入权限，请刷新环境列表重试。');
    expect(html()).not.toContain('[接入引导面板:');
    expect(html()).not.toContain('[安装计划面板:');
    expect(html()).not.toContain('创建环境并接入');
    root.unmount();
  });
});

function findByTag(root: FakeElement, tag: string): FakeElement | null {
  for (const child of root.childNodes) {
    if (child.nodeType !== 1) continue;
    if (child.tagName === tag.toUpperCase()) return child;
    const found = findByTag(child, tag);
    if (found) return found;
  }
  return null;
}
