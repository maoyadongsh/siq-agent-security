/** RuntimeBindingsPage 行为测试专用最小 DOM shim（ENT-018-BINDINGS-UI）。
 * vitest 为 node 环境且本任务不安装依赖（无 jsdom/testing-library），
 * 故提供仅覆盖 React 18 渲染/事件委托所需的最小 DOM 实现。
 *
 * 关键点：react-dom 在模块加载期计算 canUseDOM 与 isInputEventSupported
 * （isEventSupported('input') 依赖 document 上的 on* 属性），因此本模块
 * 必须在 react/react-dom 之前被 import（模块顶层即安装全局），
 * 否则文本 input 的 change 事件会走 IE 兼容路径而永不触发。
 * 交互（键盘/视口/溢出）由隔离浏览器测试覆盖，本 shim 不承担像素级断言。 */

export class FakeElement {
  nodeType = 1;
  tagName: string;
  parentNode: FakeElement | null = null;
  childNodes: FakeElement[] = [];
  attributes: Record<string, string> = {};
  listeners: Record<string, ((e?: unknown) => void)[]> = {};
  style: Record<string, string> = {};
  value = '';
  private _value = '';
  ownerDocument: unknown = null;
  constructor(tag: string) {
    this.tagName = tag.toUpperCase();
  }
  /** React updateOptions 需要 element.options（select 的 option 子节点） */
  get options(): FakeElement[] {
    return this.childNodes.filter((n) => n.tagName === 'OPTION');
  }
  /** React isSelect/isTextInputElement 按 nodeName 判断元素类型 */
  get nodeName(): string {
    return this.tagName;
  }
  /** React isTextInputElement 按 supportedInputTypes[elem.type] 判断；真实 input 默认 type=text */
  get type(): string | undefined {
    if (this.tagName === 'INPUT') return this.attributes.type ?? 'text';
    return undefined;
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
  getClientRects() {
    return [];
  }
  private matchesSimpleSelector(sel: string): boolean {
    const classMatch = sel.match(/^\.([\w-]+)$/);
    if (classMatch) return this.attributes.class?.split(' ').includes(classMatch[1]) ?? false;
    const attrMatch = sel.match(/^([\w-]+)\[([\w-]+)(?:="([^"]*)")?\]$/);
    if (attrMatch) {
      if (this.tagName !== attrMatch[1].toUpperCase()) return false;
      const attrVal = this.attributes[attrMatch[2]];
      if (attrMatch[3] !== undefined) return attrVal === attrMatch[3];
      return attrVal !== undefined;
    }
    if (/^[\w-]+$/.test(sel)) return this.tagName === sel.toUpperCase();
    return false;
  }
  private matchesDescendantSelector(sel: string): boolean {
    const parts = sel.trim().split(/\s+/);
    if (parts.length === 1) return this.matchesSimpleSelector(parts[0]);
    if (!this.matchesSimpleSelector(parts[parts.length - 1])) return false;
    let ancestor: FakeElement | null = this.parentNode;
    let idx = parts.length - 2;
    while (ancestor && idx >= 0) {
      if (ancestor.nodeType === 1 && ancestor.matchesSimpleSelector(parts[idx])) idx--;
      ancestor = ancestor.parentNode;
    }
    return idx < 0;
  }
  querySelector(sel: string): FakeElement | null {
    const match = (el: FakeElement): FakeElement | null => {
      for (const child of el.childNodes) {
        if (child.nodeType === 1) {
          if (child.matchesDescendantSelector(sel)) return child;
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
        if (child.matchesDescendantSelector(sel)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
  get innerHTML() {
    const render = (el: FakeElement): string => {
      if (el.nodeType === 3) return el.textContent ?? '';
      const attrs = Object.entries(el.attributes)
        .map(([k, v]) => ` ${k}="${v}"`)
        .join('');
      // React 对单子文本子节点直接设置宿主元素 textContent（不建文本子节点），
      // 故元素节点仅在无子节点时读取自身 textContent，避免与文本子节点重复。
      const ownText = el.childNodes.length === 0 ? (el.textContent ?? '') : '';
      return `<${el.tagName.toLowerCase()}${attrs}>${ownText}${el.childNodes.map(render).join('')}</${el.tagName.toLowerCase()}>`;
    };
    return this.childNodes.map(render).join('');
  }
}

export class FakeText extends FakeElement {
  nodeType = 3;
  constructor(text: string) {
    super('#text');
    this.textContent = text;
  }
}

const fakeDocumentBase = {
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
// react-dom isEventSupported 用 `'on'+suffix in document` 探测事件支持（如 oninput），
// 文本 input 的 change 事件依赖 isInputEventSupported 为真，否则走 IE 兼容路径永不触发。
// 用 Proxy 的 has 陷阱对任意 on* 键返回 true，使探测通过。
export const fakeDocument = new Proxy(fakeDocumentBase, {
  has(target, prop) {
    if (typeof prop === 'string' && prop.startsWith('on')) return true;
    return Reflect.has(target, prop);
  },
}) as unknown as Record<string, unknown>;

// 门户（createPortal）挂载到 body：React 用 ownerDocument.createElement 创建节点
(fakeDocument.body as FakeElement).ownerDocument = fakeDocument;
(fakeDocument.head as FakeElement).ownerDocument = fakeDocument;
(fakeDocument.documentElement as FakeElement).ownerDocument = fakeDocument;
(fakeDocument as { activeElement: FakeElement | null }).activeElement = fakeDocument.body as FakeElement;

export class FakeNode {}
export class FakeText2 extends FakeNode {}
export class FakeComment extends FakeNode {}
export class FakeElement2 extends FakeNode {}
export class FakeHTMLElement extends FakeElement2 {}
export class FakeHTMLIFrameElement extends FakeHTMLElement {}

/* 模块加载期安装全局（必须先于 react/react-dom 的 import 执行） */
const g = globalThis as Record<string, unknown>;
g.document = fakeDocument;
g.window = {
  addEventListener: () => {},
  removeEventListener: () => {},
  // react-dom canUseDOM 检查 window.document；缺失则 canUseDOM=false，
  // 导致 isInputEventSupported 永不置真，文本 input 的 change 事件走 IE 兼容路径而丢失。
  document: fakeDocument,
  location: { origin: 'http://127.0.0.1', href: 'http://127.0.0.1/' },
  Node: FakeNode,
  Text: FakeText2,
  Comment: FakeComment,
  Element: FakeElement2,
  HTMLElement: FakeHTMLElement,
  HTMLIFrameElement: FakeHTMLIFrameElement,
  getSelection: () => null,
};
g.Node = FakeNode;
g.HTMLElement = FakeHTMLElement;
g.HTMLIFrameElement = FakeHTMLIFrameElement;
g.Text = FakeText2;
g.Comment = FakeComment;
g.IS_REACT_ACT_ENVIRONMENT = true;
