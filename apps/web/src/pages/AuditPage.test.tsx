/**
 * CL-06-AUDIT-CORRELATION-UI：AuditPage 组件级定向测试（真实产品组件 + mock API）。
 *
 * 覆盖：
 * - A/B 键碰撞修复：从条件 A 切到 B 确实发出 B 查询并丢弃 A 迟到响应；
 * - 关联按钮准确参数、清空其余条件、表单同步、同条件重复不发请求；
 * - 特殊字符原值往返；身份未 ready/失败/无 audit 权限时零审计请求；
 * - 分页沿用同一条件；断连无关联动作；XSS 文本不渲染为元素；身份切换不残留旧结果；
 * - 全程仅 GET（mock 层只暴露 getListPage，无写方法被调用）。
 *
 * CL-01-AUDIT-TEST-PORTABILITY 环境说明：jsdom 不在本仓依赖中，本文件不再经
 * createRequire 绝对路径引用兄弟项目的 jsdom 副本，改用审计测试专用最小 DOM
 * （@/test-support/auditDomHarness），真实挂载 react-dom/client。harness 必须在
 * react/react-dom 之前 import——react-dom 在模块加载期计算 canUseDOM 与
 * isInputEventSupported。事件经 React 委托监听器真实派发到组件 handler；
 * 布局/可见焦点/真实 XSS 执行能力不在该 shim 覆盖范围，沿用既有隔离浏览器证据边界。
 */
import {
  type AuditElement,
  auditDocument,
  dispatchDomEvent,
  fireInput,
  restoreAuditDom,
} from '@/test-support/auditDomHarness';
import { act } from 'react';
import { afterAll, afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';
import React from 'react';
import AuditPage from './AuditPage';
import type { ListMeta } from '@/api/listMeta';
import type { AuditEvent } from '@/api/types';
import type { ConsoleContext } from '@/api/consoleContext';

/* ---------------- 模块 mock（工厂不依赖 react-dom） ---------------- */

const ctxState = vi.hoisted(() => ({
  status: 'loading' as 'loading' | 'ready' | 'error',
  data: undefined as ConsoleContext | undefined,
}));

vi.mock('@/components/ConsoleContext', () => ({
  useConsoleContext: () => ctxState,
}));

interface Call {
  path: string;
  query: Record<string, string | number | boolean | undefined> | undefined;
  d: { promise: Promise<unknown>; resolve: (v: unknown) => void; reject: (e: unknown) => void };
}
const calls: Call[] = vi.hoisted(() => [] as unknown as Call[]);

vi.mock('@/api/client', () => ({
  getListPage: vi.fn(
    (path: string, options?: { query?: Record<string, string | number | boolean | undefined> }) => {
      let resolve!: (v: unknown) => void;
      let reject!: (e: unknown) => void;
      const promise = new Promise<unknown>((res, rej) => {
        resolve = res;
        reject = rej;
      });
      calls.push({ path, query: options?.query, d: { promise, resolve, reject } });
      return promise;
    },
  ),
  describeApiError: vi.fn((_e: unknown, fallback?: string) => fallback ?? '操作失败'),
}));

const getListPageMock = (await import('@/api/client')).getListPage as unknown as {
  mock: { calls: unknown[] };
};

/* ---------------- 工具 ---------------- */

const EMPTY_META: ListMeta = { limit: 50, returned: 0, truncated: false, nextCursor: null, total: 0 };

function makeEvent(overrides: Partial<AuditEvent>): AuditEvent {
  return {
    id: 'aud-1',
    actor_type: 'user',
    actor_id: 'u-1',
    action: 'agent.confirm',
    resource_type: 'agent_asset',
    resource_id: 'agt-1',
    decision: 'allow',
    request_id: 'req-1',
    summary: {},
    created_at: '2026-09-26T00:00:00Z',
    ...overrides,
  };
}

function makeContext(overrides: Partial<ConsoleContext> = {}): ConsoleContext {
  return {
    schema_version: 'console-context/v1',
    evaluated_at: '2026-09-26T00:00:00Z',
    tenant: { id: 'tenant-a', name: 'Tenant A' },
    actor: { id: 'actor-1', type: 'user' },
    authentication: 'verified_token',
    roles: [],
    custom_role_count: 0,
    access: {
      workspace: true, overview: true, agents: true, permissions: true, findings: true,
      policies: true, changes: true, runtime_bindings: true, environments: true, audit: true, settings: true,
    },
    actions: {
      confirm_assets: false, manage_environment: false, enroll_devices: false,
      manage_policy: false, propose_change: false, approve_change: false,
    },
    ...overrides,
  };
}

function flush() {
  return act(async () => {
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 0));
  });
}

function inputById(id: string): AuditElement {
  const input = auditDocument.getElementById(id);
  if (!input) throw new Error(`未找到审计查询输入框：${id}`);
  return input;
}

/** 输入 = 经原型 value setter 写值 + 冒泡派发 input 事件（真实触发组件 onChange）。 */
function setInput(id: string, value: string) {
  const input = inputById(id);
  act(() => {
    fireInput(input, value);
  });
}

function submitForm() {
  const form = auditDocument.querySelector('form.audit-search-form');
  if (!form) throw new Error('未找到审计查询表单');
  act(() => {
    dispatchDomEvent(form, 'submit');
  });
}

function clickButton(element: AuditElement) {
  act(() => {
    dispatchDomEvent(element, 'click');
  });
}

function allButtons(): AuditElement[] {
  return auditDocument.querySelectorAll('button');
}

/** 按 aria-label 精确匹配按钮（特殊字符无法用 CSS 选择器转义，直接读属性比较）。 */
function findButtonByAriaLabel(label: string): AuditElement | null {
  return allButtons().find((b) => b.getAttribute('aria-label') === label) ?? null;
}

function allRows(): AuditElement[] {
  return auditDocument.querySelectorAll('tbody tr');
}

function findButtonByText(text: string): AuditElement | null {
  return allButtons().find((b) => b.textContent === text) ?? null;
}

let root: Root | null = null;
let container: AuditElement | null = null;

beforeEach(() => {
  calls.length = 0;
  ctxState.status = 'loading';
  ctxState.data = undefined;
  container = auditDocument.createElement('div');
  auditDocument.body.appendChild(container);
  root = createRoot(container as unknown as DocumentFragment);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.clearAllMocks();
});

afterAll(() => {
  restoreAuditDom();
});

/* ---------------- 用例 ---------------- */

it('身份未 ready / 核对失败 / 无 audit 权限时零审计请求，且文案如实区分', async () => {
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  expect(calls.length).toBe(0);
  expect(container!.textContent).toContain('正在核对审计访问权限');

  ctxState.status = 'error';
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  expect(calls.length).toBe(0);
  expect(container!.textContent).toContain('身份与权限核对失败');
  expect(container!.textContent).not.toContain('正在核对审计访问权限');

  ctxState.status = 'ready';
  ctxState.data = makeContext({ access: { ...makeContext().access, audit: false } });
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  expect(calls.length).toBe(0);
  expect(container!.textContent).toContain('当前账号无审计访问权限');
});

it('A→B 键碰撞修复：切条件确实发出 B 查询，A 迟到响应不覆盖 B 结果', async () => {
  ctxState.status = 'ready';
  ctxState.data = makeContext();
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  // 首屏（无条件）
  expect(calls.length).toBe(1);
  calls[0].d.resolve({ items: [makeEvent({ id: 'aud-init' })], meta: EMPTY_META });
  await flush();
  expect(container!.textContent).toContain('aud-init');

  // 条件 A：request_id="a&resource_id=b"，resource_id="c"
  setInput('audit-search-request_id', 'a&resource_id=b');
  setInput('audit-search-resource_id', 'c');
  submitForm();
  await flush();
  expect(calls.length).toBe(2);
  expect(calls[1].query).toMatchObject({ request_id: 'a&resource_id=b', resource_id: 'c' });
  expect(calls[1].query).not.toHaveProperty('actor_id');

  // 条件 B：request_id="a"，resource_id="b&resource_id=c"（旧 key 与 A 碰撞）
  setInput('audit-search-request_id', 'a');
  setInput('audit-search-resource_id', 'b&resource_id=c');
  submitForm();
  await flush();
  // 修复后：B 必须发出新查询（旧实现 key 碰撞 → 不会发第三个请求）
  expect(calls.length).toBe(3);
  expect(calls[2].query).toMatchObject({ request_id: 'a', resource_id: 'b&resource_id=c' });

  // A 的迟到成功响应不得覆盖 B 的加载态/结果
  calls[1].d.resolve({ items: [makeEvent({ id: 'aud-A-late' })], meta: EMPTY_META });
  await flush();
  expect(container!.textContent).not.toContain('aud-A-late');
  expect(container!.textContent).toContain('正在按当前已应用条件加载审计事件');

  // B 正常返回后展示 B 结果
  calls[2].d.resolve({ items: [makeEvent({ id: 'aud-B' })], meta: EMPTY_META });
  await flush();
  expect(container!.textContent).toContain('aud-B');
  expect(container!.textContent).not.toContain('aud-A-late');
});

it('查询同请求：只带 request_id 精确查询、清空其余条件、表单同步、同条件重复不发请求', async () => {
  ctxState.status = 'ready';
  ctxState.data = makeContext();
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  const special = '  Req-8F2A & + # "引号" 中文 ';
  calls[0].d.resolve({
    items: [makeEvent({ id: 'aud-x', request_id: special, resource_type: 'agent_asset', resource_id: 'agt-9' })],
    meta: EMPTY_META,
  });
  await flush();

  const btn = findButtonByAriaLabel(`查询同请求：${special}`);
  expect(btn).toBeTruthy();
  clickButton(btn!);
  await flush();
  expect(calls.length).toBe(2);
  // 只保留 request_id，其余六字段不发送
  expect(calls[1].query).toMatchObject({ request_id: special, limit: 50, include_total: true });
  expect(calls[1].query).not.toHaveProperty('resource_id');
  expect(calls[1].query).not.toHaveProperty('resource_type');
  expect(calls[1].query).not.toHaveProperty('actor_id');
  expect(calls[1].query).not.toHaveProperty('actor_type');
  expect(calls[1].query).not.toHaveProperty('action');
  expect(calls[1].query).not.toHaveProperty('decision');
  // 表单草稿与已应用条件同步（原值逐字）
  expect(inputById('audit-search-request_id').value).toBe(special);
  expect(inputById('audit-search-resource_id').value).toBe('');
  expect(container!.textContent).toContain(`当前已应用查询条件：请求编号 = ${special}`);

  calls[1].d.resolve({ items: [makeEvent({ id: 'aud-req-hit', request_id: special })], meta: EMPTY_META });
  await flush();
  expect(container!.textContent).toContain('aud-req-hit');

  // 同条件重复点击：不重复发请求，给出提示
  setInput('audit-search-resource_id', 'unsubmitted-draft');
  const btn2 = findButtonByAriaLabel(`查询同请求：${special}`);
  clickButton(btn2!);
  await flush();
  expect(calls.length).toBe(2);
  expect(inputById('audit-search-resource_id').value).toBe('');
  expect(container!.textContent).toContain('查询条件与当前已应用条件相同，未发起新请求');
});

it('查询同对象：resource_type + resource_id 一起查询；缺失标识行无关联动作', async () => {
  ctxState.status = 'ready';
  ctxState.data = makeContext();
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  calls[0].d.resolve({
    items: [
      makeEvent({ id: 'aud-ok', resource_type: 'environment', resource_id: 'env-dev-docker' }),
      makeEvent({ id: 'aud-noid', request_id: null, resource_id: null }),
    ],
    meta: EMPTY_META,
  });
  await flush();

  // 缺失标识行（点击前检查）：无关联按钮，保持「未提供」文本
  const rows = allRows();
  const noIdRow = rows.find((r) => r.textContent?.includes('aud-noid'))!;
  expect(noIdRow).toBeTruthy();
  expect(noIdRow.textContent).not.toContain('查询同请求');
  expect(noIdRow.textContent).not.toContain('查询同对象');
  expect(noIdRow.textContent).toContain('未提供');

  const btn = findButtonByAriaLabel('查询同对象：environment:env-dev-docker');
  expect(btn).toBeTruthy();
  clickButton(btn!);
  await flush();
  expect(calls.length).toBe(2);
  expect(calls[1].query).toMatchObject({ resource_type: 'environment', resource_id: 'env-dev-docker' });
  expect(calls[1].query).not.toHaveProperty('request_id');
});

it('分页沿用同一新条件；加载更多失败保留记录并可同游标重试', async () => {
  ctxState.status = 'ready';
  ctxState.data = makeContext();
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  calls[0].d.resolve({
    items: [makeEvent({ id: 'aud-p1' })],
    meta: { limit: 50, returned: 1, truncated: true, nextCursor: 'cur-1', total: 2 },
  });
  await flush();
  const more = findButtonByText('加载更多');
  expect(more).toBeTruthy();
  clickButton(more!);
  await flush();
  expect(calls.length).toBe(2);
  expect(calls[1].query).toMatchObject({ cursor: 'cur-1', limit: 50, include_total: true });

  // 分页失败：保留此前记录，错误提示不冒充全量成功
  calls[1].d.reject(new Error('加载更多失败'));
  await flush();
  expect(container!.textContent).toContain('aud-p1');
  expect(container!.textContent).toContain('加载更多失败');
  expect(container!.textContent).toContain('不代表全部加载成功');

  // 同游标重试
  const retry = findButtonByText('加载更多');
  clickButton(retry!);
  await flush();
  expect(calls.length).toBe(3);
  expect(calls[2].query).toMatchObject({ cursor: 'cur-1' });
  calls[2].d.resolve({
    items: [makeEvent({ id: 'aud-p2' })],
    meta: { limit: 50, returned: 1, truncated: false, nextCursor: null, total: 2 },
  });
  await flush();
  expect(container!.textContent).toContain('aud-p2');
});

it('断连无关联动作；XSS 文本按文本渲染不产生元素；全程仅 GET', async () => {
  ctxState.status = 'ready';
  ctxState.data = makeContext();
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  // 首屏失败 → 断连（VITE_DEMO_PLACEHOLDERS 未开 → 无占位行、无关联按钮）
  calls[0].d.reject(new Error('无法连接控制面 API'));
  await flush();
  expect(container!.textContent).toContain('未连接');
  expect(auditDocument.querySelectorAll('button.audit-correlation-btn').length).toBe(0);

  // 重试成功：XSS 标识按文本渲染
  const retry = findButtonByText('重试连接');
  clickButton(retry!);
  await flush();
  const xss = '<img src=x onerror=alert(1)>';
  calls[1].d.resolve({
    items: [makeEvent({ id: 'aud-xss', request_id: xss, resource_type: 'agent_asset', resource_id: 'agt-x' })],
    meta: EMPTY_META,
  });
  await flush();
  // 注：本 shim 不执行真实 HTML 解析（不托管 XSS 执行环境），此处只证明 React 未产出 img 元素。
  expect(auditDocument.querySelectorAll('img').length).toBe(0);
  expect(container!.textContent).toContain(xss);
  const xssBtn = auditDocument.querySelector(`button[aria-label="查询同请求：${xss}"]`);
  expect(xssBtn).toBeTruthy();

  // 全程仅 GET：mock 层只暴露 getListPage（GET 列表），无任何写方法被调用
  expect(getListPageMock.mock.calls.length).toBe(2);
  expect(calls.every((c) => c.path === '/audit-events')).toBe(true);
});

it.each(['tenant', 'actor-type', 'permission'] as const)('身份变化 %s 清除旧草稿与已应用条件', async (change) => {
  ctxState.status = 'ready';
  ctxState.data = makeContext();
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  setInput('audit-search-request_id', 'old-identity-query');
  submitForm();
  await flush();
  setInput('audit-search-resource_id', 'old-private-draft');
  if (change === 'tenant') ctxState.data = makeContext({ tenant: { id: 'new-tenant', name: 'New' } });
  else if (change === 'actor-type') ctxState.data = makeContext({ actor: { id: 'actor-1', type: 'service' } });
  else {
    ctxState.status = 'error';
    act(() => root!.render(React.createElement(AuditPage)));
    await flush();
    ctxState.status = 'ready';
  }
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  expect(inputById('audit-search-request_id').value).toBe('');
  expect(inputById('audit-search-resource_id').value).toBe('');
  expect(calls.at(-1)!.query).not.toHaveProperty('request_id');
});

it('身份切换：旧身份结果不残留（组合 key 变化重建结果组件）', async () => {
  ctxState.status = 'ready';
  ctxState.data = makeContext();
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  calls[0].d.resolve({ items: [makeEvent({ id: 'aud-tenant-a' })], meta: EMPTY_META });
  await flush();
  expect(container!.textContent).toContain('aud-tenant-a');

  // 切换到另一租户（同 actor）：结果组件按新身份 key 重建，重新查询
  ctxState.data = makeContext({ tenant: { id: 'tenant-b', name: 'Tenant B' } });
  act(() => root!.render(React.createElement(AuditPage)));
  await flush();
  expect(calls.length).toBe(2);
  expect(container!.textContent).not.toContain('aud-tenant-a');
  expect(container!.textContent).toContain('正在按当前已应用条件加载审计事件');
  calls[1].d.resolve({ items: [makeEvent({ id: 'aud-tenant-b' })], meta: EMPTY_META });
  await flush();
  expect(container!.textContent).toContain('aud-tenant-b');
});
