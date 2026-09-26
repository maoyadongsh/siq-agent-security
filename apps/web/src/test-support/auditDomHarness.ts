/**
 * AuditPage 组件级行为测试专用最小 DOM（CL-01-AUDIT-TEST-PORTABILITY）。
 *
 * 目的：去掉对兄弟仓库 / 绝对路径 jsdom 副本的依赖，使审计测试在独立检出本仓后
 * 仍可复现。本仓 vitest 为 node 环境且不安装 DOM 依赖，故复用仓内既有页面测试
 * 已验证的 shim 模式（src/pages/runtimeBindingPageDomShim.ts）的必要部分，只覆盖
 * 当前审计测试用到的 API，不构成通用 DOM 框架。
 *
 * 关键约束（与 react-dom 18.3 的实现一一对应）：
 * - react-dom 在「模块加载期」计算 canUseDOM 与 isEventSupported('input')，因此本模块
 *   必须早于 react/react-dom 被 import（模块顶层即安装全局），否则文本 input 的
 *   change 事件会走 IE 兼容路径而永不触发；
 * - 受控 input 的 value 必须是「原型访问器」：react-dom 的 trackValueOnNode 只在
 *   node.constructor.prototype.value 具备 get/set 时才建立值跟踪。测试用 fireInput
 *   经原型 setter 写值（绕过 react-dom 装在实例上的 tracker setter），语义等同浏览器中
 *   「用户改值」，onChange 才会真实触发；
 * - 事件按冒泡路径派发给 react-dom 的委托监听器（监听器在 createRoot 容器上），
 *   不直接调用组件内部 handler、不直接改组件状态、不做源码字符串断言。
 *
 * 能力边界：本 shim 不实现布局/几何、可见焦点、CSS 计算，也不执行真实 HTML 解析，
 * 因此不证明「可见焦点」「无横向溢出」或「XSS 不可执行」等浏览器层结论；
 * 这些沿用既有隔离浏览器证据边界，本 harness 不冒充已验证。
 */

type Listener = (event: AuditDomEvent) => void;

/** 原生样式事件对象：react-dom 的 SyntheticEvent 由它包装而来。 */
export class AuditDomEvent {
  type: string;
  target: AuditElement | null;
  currentTarget: AuditElement | AuditDocument | null = null;
  bubbles: boolean;
  cancelable: boolean;
  defaultPrevented = false;
  nativeEvent = null;
  private propagationStopped = false;

  constructor(
    type: string,
    init: { target?: AuditElement | null; bubbles?: boolean; cancelable?: boolean } = {},
  ) {
    this.type = type;
    this.target = init.target ?? null;
    this.bubbles = init.bubbles ?? true;
    this.cancelable = init.cancelable ?? true;
  }

  preventDefault(): void {
    if (this.cancelable) this.defaultPrevented = true;
  }

  stopPropagation(): void {
    this.propagationStopped = true;
  }

  stopImmediatePropagation(): void {
    this.propagationStopped = true;
  }

  isDefaultPrevented(): boolean {
    return this.defaultPrevented;
  }

  isPropagationStopped(): boolean {
    return this.propagationStopped;
  }

  persist(): void {}
}

export class AuditText {
  nodeType = 3;
  parentNode: AuditElement | null = null;
  ownerDocument: AuditDocument | null = null;
  private text: string;

  constructor(text: string) {
    this.text = String(text);
  }

  get textContent(): string {
    return this.text;
  }

  set textContent(value: string) {
    this.text = String(value);
  }

  /** react-dom commitTextUpdate 走 nodeValue。 */
  get nodeValue(): string {
    return this.text;
  }

  set nodeValue(value: string) {
    this.text = String(value);
  }

  get data(): string {
    return this.text;
  }

  set data(value: string) {
    this.text = String(value);
  }
}

/** 注释节点（nodeType 8）：react-dom 在空文本/hydration 标记处使用。 */
export class AuditComment extends AuditText {
  nodeType = 8;
}

export type AuditNode = AuditElement | AuditText;

export class AuditElement {
  nodeType = 1;
  tagName: string;
  parentNode: AuditElement | null = null;
  childNodes: AuditNode[] = [];
  attributes: Record<string, string> = {};
  listeners: Record<string, Listener[]> = {};
  style: Record<string, string> = {};
  ownerDocument: AuditDocument | null = null;
  private ownText = '';
  private fieldValue = '';

  constructor(tag: string) {
    this.tagName = tag.toUpperCase();
  }

  /** react-dom 按 nodeName 判断元素类别（isTextInputElement 自行转小写）。 */
  get nodeName(): string {
    return this.tagName;
  }

  /** isTextInputElement 按 elem.type 查 supportedInputTypes；真实 input 默认 type=text。 */
  get type(): string | undefined {
    if (this.tagName === 'INPUT') return this.attributes.type ?? 'text';
    return undefined;
  }

  set type(value: string) {
    this.attributes.type = String(value);
  }

  get firstChild(): AuditNode | null {
    return this.childNodes[0] ?? null;
  }

  get lastChild(): AuditNode | null {
    return this.childNodes[this.childNodes.length - 1] ?? null;
  }

  /**
   * 受控字段值。必须是原型访问器：react-dom trackValueOnNode 要求
   * node.constructor.prototype.value 具备 get/set，才会安装值跟踪器。
   */
  get value(): string {
    return this.fieldValue;
  }

  set value(value: string) {
    this.fieldValue = String(value);
  }

  /** 与真实 DOM 一致：自身文本 + 全部后代文本拼接。 */
  get textContent(): string {
    let out = this.ownText;
    for (const child of this.childNodes) out += child.textContent;
    return out;
  }

  /** 与真实 DOM 一致：设置 textContent 会替换全部子节点。 */
  set textContent(value: string) {
    const previous = this.childNodes;
    this.ownText = String(value);
    this.childNodes = [];
    for (const child of previous) child.parentNode = null;
  }

  appendChild(node: AuditNode): AuditNode {
    return this.insertBefore(node, null);
  }

  insertBefore(node: AuditNode, reference: AuditNode | null): AuditNode {
    if (node.parentNode) node.parentNode.removeChild(node);
    const at = reference ? this.childNodes.indexOf(reference) : this.childNodes.length;
    this.childNodes.splice(at < 0 ? this.childNodes.length : at, 0, node);
    node.parentNode = this;
    return node;
  }

  removeChild(node: AuditNode): AuditNode {
    const at = this.childNodes.indexOf(node);
    if (at >= 0) this.childNodes.splice(at, 1);
    node.parentNode = null;
    return node;
  }

  remove(): void {
    this.parentNode?.removeChild(this);
  }

  setAttribute(name: string, value: string): void {
    this.attributes[name] = String(value);
  }

  removeAttribute(name: string): void {
    delete this.attributes[name];
  }

  getAttribute(name: string): string | null {
    return this.attributes[name] ?? null;
  }

  hasAttribute(name: string): boolean {
    return name in this.attributes;
  }

  addEventListener(type: string, listener: Listener): void {
    (this.listeners[type] ??= []).push(listener);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter((fn) => fn !== listener);
  }

  attachEvent(): void {}
  detachEvent(): void {}
  focus(): void {}
  blur(): void {}
  getClientRects(): unknown[] {
    return [];
  }

  querySelector(selector: string): AuditElement | null {
    return this.querySelectorAll(selector)[0] ?? null;
  }

  querySelectorAll(selector: string): AuditElement[] {
    const chain = parseSelectorChain(selector);
    if (!chain) throw new Error(`auditDomHarness 不支持的 CSS 选择器：${selector}`);
    const out: AuditElement[] = [];
    const walk = (el: AuditElement) => {
      for (const child of el.childNodes) {
        if (child.nodeType !== 1) continue;
        const element = child as AuditElement;
        if (matchesChain(element, chain)) out.push(element);
        walk(element);
      }
    };
    walk(this);
    return out;
  }

  /** 仅用于失败诊断；不参与断言。 */
  get innerHTML(): string {
    const render = (node: AuditNode): string => {
      if (node instanceof AuditText) return node.textContent;
      const attrs = Object.entries(node.attributes)
        .map(([k, v]) => ` ${k}="${v}"`)
        .join('');
      return `<${node.tagName.toLowerCase()}${attrs}>${node.childNodes.map(render).join('')}</${node.tagName.toLowerCase()}>`;
    };
    return this.childNodes.map(render).join('');
  }
}

export class AuditDocument {
  nodeType = 9;
  body: AuditElement;
  head: AuditElement;
  documentElement: AuditElement;
  activeElement: AuditElement;
  listeners: Record<string, Listener[]> = {};

  constructor() {
    this.documentElement = new AuditElement('html');
    this.head = new AuditElement('head');
    this.body = new AuditElement('body');
    this.documentElement.appendChild(this.head);
    this.documentElement.appendChild(this.body);
    for (const element of [this.documentElement, this.head, this.body]) {
      element.ownerDocument = this;
    }
    this.activeElement = this.body;
  }

  createElement(tag: string): AuditElement {
    const element = new AuditElement(tag);
    element.ownerDocument = this;
    return element;
  }

  createElementNS(_namespace: string, tag: string): AuditElement {
    return this.createElement(tag);
  }

  createTextNode(text: string): AuditText {
    const node = new AuditText(text);
    node.ownerDocument = this;
    return node;
  }

  createComment(text: string): AuditComment {
    const node = new AuditComment(text);
    node.ownerDocument = this;
    return node;
  }

  getElementById(id: string): AuditElement | null {
    const walk = (el: AuditElement): AuditElement | null => {
      for (const child of el.childNodes) {
        if (child.nodeType !== 1) continue;
        const element = child as AuditElement;
        if (element.attributes.id === id) return element;
        const found = walk(element);
        if (found) return found;
      }
      return null;
    };
    return walk(this.documentElement);
  }

  querySelector(selector: string): AuditElement | null {
    return this.documentElement.querySelector(selector);
  }

  querySelectorAll(selector: string): AuditElement[] {
    return this.documentElement.querySelectorAll(selector);
  }

  addEventListener(type: string, listener: Listener): void {
    (this.listeners[type] ??= []).push(listener);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter((fn) => fn !== listener);
  }
}

/* ---------------- 选择器（仅覆盖审计测试用到的形态） ---------------- */

interface CompoundSelector {
  tag: string | null;
  classes: string[];
  attributes: { name: string; value: string | null }[];
}

/** 按空白切分后代组合器，方括号/引号内不切分（aria-label 值可含空格）。 */
function splitSelector(selector: string): string[] {
  const parts: string[] = [];
  let buffer = '';
  let depth = 0;
  let quote: string | null = null;
  for (const char of selector.trim()) {
    if (quote) {
      buffer += char;
      if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      buffer += char;
      continue;
    }
    if (char === '[') depth += 1;
    if (char === ']') depth -= 1;
    if (/\s/.test(char) && depth === 0) {
      if (buffer) parts.push(buffer);
      buffer = '';
      continue;
    }
    buffer += char;
  }
  if (buffer) parts.push(buffer);
  return parts;
}

function parseCompound(selector: string): CompoundSelector | null {
  let rest = selector;
  let tag: string | null = null;
  const tagMatch = /^([a-zA-Z][\w-]*)/.exec(rest);
  if (tagMatch) {
    tag = tagMatch[1].toUpperCase();
    rest = rest.slice(tagMatch[0].length);
  }
  const classes: string[] = [];
  for (;;) {
    const match = /^\.([\w-]+)/.exec(rest);
    if (!match) break;
    classes.push(match[1]);
    rest = rest.slice(match[0].length);
  }
  const attributes: { name: string; value: string | null }[] = [];
  for (;;) {
    const match = /^\[([^\]=\s]+)(?:=("([^"]*)"|'([^']*)'|([^\]\s]+)))?\]/.exec(rest);
    if (!match) break;
    attributes.push({ name: match[1], value: match[3] ?? match[4] ?? match[5] ?? null });
    rest = rest.slice(match[0].length);
  }
  if (rest !== '') return null;
  return { tag, classes, attributes };
}

function parseSelectorChain(selector: string): CompoundSelector[] | null {
  const parts = splitSelector(selector);
  if (parts.length === 0) return null;
  const chain: CompoundSelector[] = [];
  for (const part of parts) {
    const compound = parseCompound(part);
    if (!compound) return null;
    chain.push(compound);
  }
  return chain;
}

function matchesCompound(element: AuditElement, compound: CompoundSelector): boolean {
  if (compound.tag && element.tagName !== compound.tag) return false;
  for (const className of compound.classes) {
    if (!element.attributes.class?.split(' ').includes(className)) return false;
  }
  for (const { name, value } of compound.attributes) {
    const actual = element.attributes[name];
    if (value === null ? actual === undefined : actual !== value) return false;
  }
  return true;
}

function matchesChain(element: AuditElement, chain: CompoundSelector[]): boolean {
  if (!matchesCompound(element, chain[chain.length - 1])) return false;
  let ancestor = element.parentNode;
  let index = chain.length - 2;
  while (ancestor && index >= 0) {
    if (matchesCompound(ancestor, chain[index])) index -= 1;
    ancestor = ancestor.parentNode;
  }
  return index < 0;
}

/* ---------------- 事件派发（冒泡到 react-dom 的委托监听器） ---------------- */

export function dispatchDomEvent(
  target: AuditElement,
  type: string,
  init: { bubbles?: boolean; cancelable?: boolean } = {},
): AuditDomEvent {
  const event = new AuditDomEvent(type, {
    target,
    bubbles: init.bubbles ?? true,
    cancelable: init.cancelable ?? true,
  });
  const chain: (AuditElement | AuditDocument)[] = [];
  let node: AuditElement | null = target;
  while (node) {
    chain.push(node);
    node = node.parentNode;
  }
  if (target.ownerDocument) chain.push(target.ownerDocument);

  for (const current of chain) {
    event.currentTarget = current;
    for (const listener of [...(current.listeners[type] ?? [])]) {
      listener(event);
      if (event.isPropagationStopped()) break;
    }
    if (event.isPropagationStopped() || !event.bubbles) break;
  }
  return event;
}

/**
 * 模拟用户在受控文本框中输入：经「原型」value setter 写值（绕过 react-dom 装在
 * 实例上的值跟踪 setter，等同于真实浏览器中用户改值），再冒泡派发 input 事件。
 */
export function fireInput(element: AuditElement, value: string): AuditDomEvent {
  const descriptor = Object.getOwnPropertyDescriptor(AuditElement.prototype, 'value');
  if (descriptor?.set) descriptor.set.call(element, value);
  else element.value = value;
  return dispatchDomEvent(element, 'input');
}

/* ---------------- 全局安装（必须早于 react/react-dom 的模块加载） ---------------- */

export const auditDocument = new AuditDocument();

interface SavedGlobal {
  present: boolean;
  value: unknown;
}

const savedGlobals = new Map<string, SavedGlobal>();
const globals = globalThis as Record<string, unknown>;

function installGlobal(key: string, value: unknown): void {
  if (!savedGlobals.has(key)) {
    savedGlobals.set(key, { present: key in globals, value: globals[key] });
  }
  globals[key] = value;
}

class AuditNodeBase {}
class AuditElementBase extends AuditNodeBase {}
class AuditCommentBase extends AuditElementBase {}
/** react-dom getActiveElementDeep 会对 window.HTMLIFrameElement 做 instanceof，必须有该构造器。 */
class AuditHTMLIFrameElementBase extends AuditElementBase {}

// react-dom isEventSupported 用 `'on'+suffix in document` 探测事件支持（如 oninput）；
// 文本 input 的 change 事件依赖 isInputEventSupported 为真，否则走 IE 兼容路径永不触发。
// 用 Proxy 的 has 陷阱对任意 on* 键返回真，使探测通过（全局与 window.document 同一实例）。
const documentProxy = new Proxy(auditDocument, {
  has(target, prop) {
    if (typeof prop === 'string' && prop.startsWith('on')) return true;
    return Reflect.has(target, prop);
  },
}) as AuditDocument;

installGlobal('IS_REACT_ACT_ENVIRONMENT', true);
installGlobal('document', documentProxy);
installGlobal('window', {
  document: documentProxy,
  location: { origin: 'http://127.0.0.1:8600', href: 'http://127.0.0.1:8600/audit' },
  Node: AuditNodeBase,
  Element: AuditElementBase,
  HTMLElement: AuditElementBase,
  Text: AuditElementBase,
  Comment: AuditCommentBase,
  HTMLIFrameElement: AuditHTMLIFrameElementBase,
  getSelection: () => null,
  addEventListener: () => {},
  removeEventListener: () => {},
});
installGlobal('Node', AuditNodeBase);
installGlobal('Element', AuditElementBase);
installGlobal('HTMLElement', AuditElementBase);
installGlobal('Text', AuditElementBase);
installGlobal('Comment', AuditCommentBase);
installGlobal('HTMLIFrameElement', AuditHTMLIFrameElementBase);

/** 恢复本模块安装过的全部全局，避免影响同进程后续测试文件。 */
export function restoreAuditDom(): void {
  for (const [key, saved] of savedGlobals) {
    if (saved.present) globals[key] = saved.value;
    else delete globals[key];
  }
  savedGlobals.clear();
  auditDocument.body.childNodes = [];
}
