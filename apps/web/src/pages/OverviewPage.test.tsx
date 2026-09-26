/** OverviewPage 行为测试（ENT-018-OVERVIEW）。
 * vitest 为 node 环境且本任务不安装依赖，故使用最小 DOM shim + react-dom/client
 * 做真实渲染行为测试（非源码字符串匹配）；交互（键盘/视口）由隔离浏览器测试覆盖。 */
import { describe, expect, it, vi, beforeAll, afterAll } from 'vitest';

/* ---------------- 最小 DOM shim（仅覆盖 React 18 渲染所需） ---------------- */
class FakeElement {
  nodeType = 1;
  tagName: string;
  parentNode: FakeElement | null = null;
  childNodes: FakeElement[] = [];
  attributes: Record<string, string> = {};
  listeners: Record<string, ((e?: unknown) => void)[]> = {};
  style: Record<string, string> = {};
  private _value = '';
  ownerDocument: unknown = null;
  constructor(tag: string) {
    this.tagName = tag.toUpperCase();
  }
  get textContent() {
    return this._value;
  }
  set textContent(v: string) {
    this._value = v;
  }
  get nodeValue() {
    return this._value;
  }
  set nodeValue(v: string) {
    this._value = v;
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
    const match = (el: FakeElement): FakeElement | null => {
      for (const child of el.childNodes) {
        if (child.nodeType === 1) {
          if (sel.startsWith('.') && child.attributes.class?.split(' ').includes(sel.slice(1))) return child;
          const found = match(child);
          if (found) return found;
        }
      }
      return null;
    };
    return match(this);
  }
  querySelectorAll(sel: string): FakeElement[] {
    const out: FakeElement[] = [];
    const walk = (el: FakeElement) => {
      for (const child of el.childNodes) {
        if (child.nodeType !== 1) continue;
        if (sel.startsWith('.') && child.attributes.class?.split(' ').includes(sel.slice(1))) out.push(child);
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
      // React 对单子文本子节点直接设置宿主元素 textContent（不建文本子节点），
      // 故所有节点都读取自身 textContent（文本节点即其值；元素节点仅在 React 直设时非空）。
      const text = el.textContent ?? '';
      return `<${el.tagName.toLowerCase()}${attrs}>${text}${el.childNodes.map(render).join('')}</${el.tagName.toLowerCase()}>`;
    };
    return this.childNodes.map(render).join('');
  }
}
class FakeText extends FakeElement {
  nodeType = 3;
  constructor(text: string) {
    super('#text');
    this.textContent = text;
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
  addEventListener: () => {},
  removeEventListener: () => {},
};
class FakeNode {}
class FakeText2 extends FakeNode {}
class FakeComment extends FakeNode {}
class FakeElement2 extends FakeNode {}
class FakeHTMLElement extends FakeElement2 {}
class FakeHTMLIFrameElement extends FakeHTMLElement {}
beforeAll(() => {
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
  };
  (globalThis as Record<string, unknown>).window = win;
  (globalThis as Record<string, unknown>).Node = FakeNode;
  (globalThis as Record<string, unknown>).HTMLElement = FakeHTMLElement;
  (globalThis as Record<string, unknown>).HTMLIFrameElement = FakeHTMLIFrameElement;
  (globalThis as Record<string, unknown>).Text = FakeText2;
  (globalThis as Record<string, unknown>).Comment = FakeComment;
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
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
const overviewMock = vi.fn();
vi.mock('@/api/client', () => ({
  api: { overview: (...args: unknown[]) => overviewMock(...args) },
  ApiError: class ApiError extends Error {
    status = 0;
    constructor(message: string) {
      super(message);
    }
  },
}));
const contextMock = vi.fn();
vi.mock('@/api/consoleContext', async () => {
  const actual = await vi.importActual<typeof import('@/api/consoleContext')>('@/api/consoleContext');
  return { ...actual, getConsoleContext: (...args: unknown[]) => contextMock(...args) };
});

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import OverviewPage from './OverviewPage';
import { ConsoleContextProvider } from '@/components/ConsoleContext';
import { accessKeys, actionKeys, type ConsoleContext } from '@/api/consoleContext';

function makeContext(granted: string[]): ConsoleContext {
  return {
    schema_version: 'console-context/v1',
    evaluated_at: '2026-09-25T01:00:00Z',
    tenant: { id: 't1', name: '组织一' },
    actor: { id: 'u1', type: 'user' },
    authentication: 'verified_token',
    roles: [{ code: 'viewer', label: '只读查看者', description: '只读' }],
    custom_role_count: 0,
    access: Object.fromEntries(accessKeys.map((k) => [k, granted.includes(k)])) as ConsoleContext['access'],
    actions: Object.fromEntries(actionKeys.map((k) => [k, false])) as ConsoleContext['actions'],
  };
}

const ALL_ACCESS = [...accessKeys];

async function render(granted: string[] | ConsoleContext = ALL_ACCESS) {
  contextMock.mockResolvedValue(
    granted instanceof Array ? makeContext(granted) : granted,
  );
  const container = new FakeElement('div');
  container.ownerDocument = fakeDocument;
  const root: Root = createRoot(container as unknown as DocumentFragment);
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={['/overview']}>
        <ConsoleContextProvider>
          <OverviewPage />
        </ConsoleContextProvider>
      </MemoryRouter>,
    );
  });
  // React 18 事件委托：监听器挂在根容器，点击需经容器派发并携带 target。
  const click = (target: FakeElement) => {
    let defaultPrevented = false;
    const event = {
      type: 'click',
      target,
      currentTarget: container,
      nativeEvent: null,
      bubbles: true,
      cancelable: true,
      preventDefault() {
        defaultPrevented = true;
      },
      stopPropagation() {},
      stopImmediatePropagation() {},
      isDefaultPrevented: () => defaultPrevented,
      isPropagationStopped: () => false,
      persist() {},
    };
    for (const fn of container.listeners.click ?? []) fn(event);
  };
  return { container, root, html: () => container.innerHTML, click };
}

describe('四主入口与次级入口', () => {
  it('四主入口标签、URL 与顺序正确', async () => {
    overviewMock.mockResolvedValue({ agents: 1, candidates: 0, open_findings: 0, critical_findings: 0, environments: 0, edges_online: 0, policies: 0 });
    const { container, html, root } = await render();
    await act(async () => {});
    const links = container.querySelectorAll('.quick-tile');
    const mainLinks = links.slice(0, 4);
    expect(mainLinks.map((l) => l.attributes.href)).toEqual(['/agents', '/permissions', '/findings', '/audit']);
    expect(html()).toContain('资产');
    expect(html()).toContain('权限');
    expect(html()).toContain('安全');
    expect(html()).toContain('审计');
    root.unmount();
  });

  it('次级入口保留且默认折叠（details 无 open 属性）', async () => {
    overviewMock.mockResolvedValue({ agents: 0, candidates: 0, open_findings: 0, critical_findings: 0, environments: 0, edges_online: 0, policies: 0 });
    const { container, html, root } = await render();
    await act(async () => {});
    expect(html()).toContain('管理与高级功能');
    expect(html()).toContain('策略中心');
    expect(html()).toContain('变更中心');
    const details = container.querySelectorAll('.entoverview-secondary');
    expect(details.length).toBe(1);
    expect(details[0].attributes.open).toBeUndefined();
    root.unmount();
  });

  it('逐项权限过滤：无权限入口不出现，空分组不显示', async () => {
    overviewMock.mockResolvedValue({ agents: 0, candidates: 0, open_findings: 0, critical_findings: 0, environments: 0, edges_online: 0, policies: 0 });
    const { container, html, root } = await render(['agents', 'policies']);
    await act(async () => {});
    const links = container.querySelectorAll('.quick-tile');
    expect(links.map((l) => l.attributes.href)).toEqual(['/agents', '/policies']);
    expect(html()).not.toContain('href="/permissions"');
    expect(html()).not.toContain('href="/changes"');
    root.unmount();
  });

  it('无任何可访问入口时不显示空壳分组', async () => {
    overviewMock.mockResolvedValue({ agents: 0, candidates: 0, open_findings: 0, critical_findings: 0, environments: 0, edges_online: 0, policies: 0 });
    const { container, html, root } = await render([]);
    await act(async () => {});
    expect(container.querySelectorAll('.quick-tile').length).toBe(0);
    expect(html()).not.toContain('entoverview-secondary');
    root.unmount();
  });

  it('管理员角色名称不覆盖实际权限', async () => {
    overviewMock.mockResolvedValue({ agents: 0, candidates: 0, open_findings: 0, critical_findings: 0, environments: 0, edges_online: 0, policies: 0 });
    const ctx = makeContext(['agents']);
    ctx.roles = [{ code: 'admin', label: '管理员', description: '' }];
    const { container, root } = await render(ctx);
    await act(async () => {});
    const links = container.querySelectorAll('.quick-tile');
    expect(links.map((l) => l.attributes.href)).toEqual(['/agents']);
    root.unmount();
  });
});

describe('统计加载/真实 0/缺失异常/失败', () => {
  it('加载中不显示伪零值', async () => {
    let resolve!: (v: unknown) => void;
    overviewMock.mockReturnValue(new Promise((r) => (resolve = r)));
    const { html, root } = await render();
    expect(html()).toContain('加载中…');
    expect(html()).not.toContain('>0<');
    await act(async () => {
      resolve({ agents: 0, candidates: 0, open_findings: 0, critical_findings: 0, environments: 0, edges_online: 0, policies: 0 });
    });
    expect(html()).not.toContain('加载中…');
    root.unmount();
  });

  it.each([null, false, 0, '', []].map((value) => ({ value })))('非对象响应 $value 显示协议错误及重试，不冒充已连接', async ({ value }) => {
    overviewMock.mockResolvedValue(value);
    const { html, root } = await render();
    await act(async () => {});
    expect(html()).toContain('统计响应格式异常');
    expect(html()).toContain('重试连接');
    expect(html()).not.toContain('stats-grid');
    root.unmount();
  });

  it('成功返回真实 0 时显示 0 且不解释为已安全', async () => {
    overviewMock.mockResolvedValue({ agents: 0, candidates: 0, open_findings: 0, critical_findings: 0, environments: 0, edges_online: 0, policies: 0 });
    const { html, root } = await render();
    await act(async () => {});
    const values = html().match(/stat-value[^>]*>0</g);
    expect(values?.length).toBe(7);
    expect(html()).not.toMatch(/已安全|没有风险|已全面保护/);
    expect(html()).toContain('设备心跳正常不等于已完成盘点或运行时防护已核验');
    root.unmount();
  });

  it('缺失/负值/非数字显示"未知/未提供"并报告响应异常，不转 0', async () => {
    overviewMock.mockResolvedValue({ agents: -1, candidates: 2.5, open_findings: Number.NaN, critical_findings: 0, environments: 1, edges_online: 0, policies: 0 });
    const { html, root } = await render();
    await act(async () => {});
    expect(html()).toContain('未知/未提供');
    expect(html()).toContain('部分统计数值缺失或异常');
    expect(html()).toContain('agents');
    expect(html()).toContain('candidates');
    expect(html()).toContain('open_findings');
    root.unmount();
  });

  it('请求失败显示错误与重试入口，不显示历史统计', async () => {
    overviewMock.mockRejectedValue(Object.assign(new Error('boom'), { name: 'ApiError' }));
    const { html, root } = await render();
    await act(async () => {});
    expect(html()).toContain('未连接 — 控制面暂不可达');
    expect(html()).toContain('重试连接');
    expect(html()).not.toContain('stats-grid');
    root.unmount();
  });

  it('重试成功清除旧错误并恢复统计', async () => {
    overviewMock.mockRejectedValueOnce(Object.assign(new Error('boom'), { name: 'ApiError' }));
    overviewMock.mockResolvedValueOnce({ agents: 3, candidates: 0, open_findings: 0, critical_findings: 0, environments: 0, edges_online: 0, policies: 0 });
    const { container, html, root, click } = await render();
    await act(async () => {});
    expect(html()).toContain('未连接 — 控制面暂不可达');
    const retry = container.querySelectorAll('.btn')[0];
    await act(async () => {
      click(retry);
    });
    await act(async () => {});
    expect(html()).not.toContain('未连接 — 控制面暂不可达');
    expect(html()).toContain('>3<');
    root.unmount();
  });

  it('不把心跳/资产数量/风险零值推导为防护已生效', async () => {
    overviewMock.mockResolvedValue({ agents: 10, candidates: 0, open_findings: 0, critical_findings: 0, environments: 2, edges_online: 5, policies: 4 });
    const { html, root } = await render();
    await act(async () => {});
    expect(html()).not.toMatch(/防护已生效|已受保护|自动完成隔离/);
    expect(html()).toContain('设备心跳正常不等于已完成盘点或运行时防护已核验');
    root.unmount();
  });
});
