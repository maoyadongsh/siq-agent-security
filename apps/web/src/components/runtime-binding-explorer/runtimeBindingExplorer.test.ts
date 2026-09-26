import { describe, expect, it } from 'vitest';
import type { AgentInstance, RuntimeBindingRow } from '@/api/types';
import {
  EMPTY_BINDING_FILTERS,
  IDLE_INSTANCE_STATE,
  applyInstanceResponse,
  beginInstanceRequest,
  filterBindings,
  hasActiveBindingFilters,
  instanceBelongsToCurrentAgent,
  invalidateInstanceRequest,
  listBindingBackends,
  listBindingEnvironments,
  optionHasId,
  statusTagClass,
  textOrMissing,
} from './runtimeBindingExplorer';

function binding(overrides: Partial<RuntimeBindingRow> = {}): RuntimeBindingRow {
  return {
    id: 'rb-0001',
    tenant_id: 't1',
    environment_id: 'env-1',
    agent_instance_id: 'inst-1',
    asset_id: 'agt-1',
    backend: 'openshell-cli',
    backend_target_id: 'target-1',
    attestation: { backend_version: 'v0.0.83' },
    status: 'active',
    created_at: '2026-09-01T00:00:00Z',
    revoked_at: null,
    ...overrides,
  };
}

function instance(id: string): AgentInstance {
  return {
    id,
    runtime: 'hermes',
    version: null,
    artifact_digest: null,
    location: {},
    status: 'running',
    observed_at: null,
  };
}

describe('AND 组合筛选', () => {
  const rows = [
    binding({ id: 'rb-1', environment_id: 'env-1', backend: 'openshell-cli', status: 'active', asset_id: 'agt-1', agent_instance_id: 'inst-1', backend_target_id: 'target-1' }),
    binding({ id: 'rb-2', environment_id: 'env-2', backend: 'hermes-sandbox', status: 'revoked', asset_id: 'agt-2', agent_instance_id: 'inst-2', backend_target_id: 'target-2' }),
    binding({ id: 'rb-3', environment_id: 'env-1', backend: 'openshell-cli', status: 'active', asset_id: 'agt-3', agent_instance_id: 'inst-3', backend_target_id: 'target-3' }),
  ];

  it('空筛选返回全部已加载记录', () => {
    expect(filterBindings(rows, EMPTY_BINDING_FILTERS)).toHaveLength(3);
  });

  it('状态 + 后端 + 环境 AND 组合', () => {
    const result = filterBindings(rows, { ...EMPTY_BINDING_FILTERS, status: 'active', backend: 'openshell-cli', environment: 'env-1' });
    expect(result.map((r) => r.id).sort()).toEqual(['rb-1', 'rb-3']);
  });

  it('文本搜索命中绑定/资产/实例/目标 ID（大小写不敏感）', () => {
    expect(filterBindings(rows, { ...EMPTY_BINDING_FILTERS, query: 'AGT-2' }).map((r) => r.id)).toEqual(['rb-2']);
    expect(filterBindings(rows, { ...EMPTY_BINDING_FILTERS, query: 'target-3' }).map((r) => r.id)).toEqual(['rb-3']);
    expect(filterBindings(rows, { ...EMPTY_BINDING_FILTERS, query: 'inst-1' }).map((r) => r.id)).toEqual(['rb-1']);
  });

  it('不同环境/实例/目标的同名记录不合并', () => {
    const sameName = [
      binding({ id: 'a', environment_id: 'env-1', agent_instance_id: 'inst-x', backend_target_id: 'tgt' }),
      binding({ id: 'b', environment_id: 'env-2', agent_instance_id: 'inst-x', backend_target_id: 'tgt' }),
      binding({ id: 'c', environment_id: 'env-1', agent_instance_id: 'inst-y', backend_target_id: 'tgt' }),
    ];
    // 同实例同目标但不同环境：三条都保留
    expect(filterBindings(sameName, { ...EMPTY_BINDING_FILTERS, environment: 'env-1' }).map((r) => r.id).sort()).toEqual(['a', 'c']);
    expect(filterBindings(sameName, { ...EMPTY_BINDING_FILTERS, query: 'inst-x' }).map((r) => r.id).sort()).toEqual(['a', 'b']);
  });

  it('无匹配返回空数组', () => {
    expect(filterBindings(rows, { ...EMPTY_BINDING_FILTERS, status: 'active', environment: 'env-2' })).toHaveLength(0);
  });

  it('hasActiveBindingFilters 识别是否启用筛选', () => {
    expect(hasActiveBindingFilters(EMPTY_BINDING_FILTERS)).toBe(false);
    expect(hasActiveBindingFilters({ ...EMPTY_BINDING_FILTERS, status: 'active' })).toBe(true);
    expect(hasActiveBindingFilters({ ...EMPTY_BINDING_FILTERS, query: '   ' })).toBe(false);
  });
});

describe('后端/环境推导（仅已加载数据）', () => {
  it('后端类型去重排序', () => {
    const rows = [
      binding({ backend: 'b' }),
      binding({ backend: 'a' }),
      binding({ backend: 'b' }),
    ];
    expect(listBindingBackends(rows)).toEqual(['a', 'b']);
  });

  it('环境以 environment_id 为值（不猜测名称）', () => {
    const rows = [binding({ environment_id: 'env-2' }), binding({ environment_id: 'env-1' })];
    expect(listBindingEnvironments(rows)).toEqual(['env-1', 'env-2']);
  });
});

describe('安全枚举与缺失字段', () => {
  it('已知状态映射标签类', () => {
    expect(statusTagClass('active')).toBe('tag-ok');
    expect(statusTagClass('revoked')).toBe('tag-err');
  });

  it('未知状态返回空类（保留原文，不冒充 active/revoked 或终态）', () => {
    expect(statusTagClass('pending')).toBe('');
    expect(statusTagClass('__proto__')).toBe('');
    expect(statusTagClass('constructor')).toBe('');
  });

  it('缺失/空字段显示「未提供」', () => {
    expect(textOrMissing(null)).toBe('未提供');
    expect(textOrMissing('')).toBe('未提供');
    expect(textOrMissing('x')).toBe('x');
  });
});

describe('选项状态', () => {
  it('optionHasId 仅当 ready 且 id 属于本次结果', () => {
    const ready = { status: 'ready' as const, items: [{ id: 'a' }, { id: 'b' }], error: null };
    expect(optionHasId(ready, 'a')).toBe(true);
    expect(optionHasId(ready, 'c')).toBe(false);
    expect(optionHasId(ready, '')).toBe(false);
    const loading = { status: 'loading' as const, items: [{ id: 'a' }], error: null };
    expect(optionHasId(loading, 'a')).toBe(false);
  });
});

describe('实例请求竞态（纯模型）', () => {
  it('切换资产递增序号并清空旧实例', () => {
    const s0 = IDLE_INSTANCE_STATE;
    const sA = beginInstanceRequest(s0, 'agt-A');
    expect(sA.seq).toBe(s0.seq + 1);
    expect(sA.status).toBe('loading');
    expect(sA.items).toEqual([]);
  });

  it('A 未完成时切换 B：B 先返回、A 后返回，最终仍是 B', () => {
    let s = beginInstanceRequest(IDLE_INSTANCE_STATE, 'agt-A'); // seq=1
    const seqA = s.seq;
    // 切换到 B
    s = beginInstanceRequest(s, 'agt-B'); // seq=2
    const seqB = s.seq;
    // B 先返回
    s = applyInstanceResponse(s, seqB, true, [instance('inst-B')], null);
    expect(s.items.map((i) => i.id)).toEqual(['inst-B']);
    expect(s.agentId).toBe('agt-B');
    // A 后返回（旧序号）→ 被忽略
    s = applyInstanceResponse(s, seqA, true, [instance('inst-A')], null);
    expect(s.items.map((i) => i.id)).toEqual(['inst-B']);
    expect(s.agentId).toBe('agt-B');
  });

  it('A 旧请求失败不覆盖 B 成功', () => {
    let s = beginInstanceRequest(IDLE_INSTANCE_STATE, 'agt-A'); // seq=1
    const seqA = s.seq;
    s = beginInstanceRequest(s, 'agt-B'); // seq=2
    const seqB = s.seq;
    s = applyInstanceResponse(s, seqB, true, [instance('inst-B')], null);
    // A 失败（旧序号）→ 忽略
    s = applyInstanceResponse(s, seqA, false, [], 'A 加载失败');
    expect(s.status).toBe('ready');
    expect(s.items.map((i) => i.id)).toEqual(['inst-B']);
    expect(s.error).toBeNull();
  });

  it('清空资产/关闭表单后旧结果失效', () => {
    let s = beginInstanceRequest(IDLE_INSTANCE_STATE, 'agt-A'); // seq=1
    const seqA = s.seq;
    s = invalidateInstanceRequest(s); // seq=2
    expect(s.status).toBe('idle');
    expect(s.agentId).toBeNull();
    // A 的迟到成功响应 → 忽略
    s = applyInstanceResponse(s, seqA, true, [instance('inst-A')], null);
    expect(s.status).toBe('idle');
    expect(s.items).toEqual([]);
  });

  it('当前实例属于当前资产的这次成功结果', () => {
    let s = beginInstanceRequest(IDLE_INSTANCE_STATE, 'agt-A');
    s = applyInstanceResponse(s, s.seq, true, [instance('inst-A1'), instance('inst-A2')], null);
    expect(instanceBelongsToCurrentAgent(s, 'agt-A', 'inst-A1')).toBe(true);
    expect(instanceBelongsToCurrentAgent(s, 'agt-A', 'inst-A9')).toBe(false);
    expect(instanceBelongsToCurrentAgent(s, 'agt-B', 'inst-A1')).toBe(false);
    expect(instanceBelongsToCurrentAgent(s, 'agt-A', '')).toBe(false);
  });
});
