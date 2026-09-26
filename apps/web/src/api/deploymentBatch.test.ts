import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, get, post } from './client';
import {
  createBatchDraft, executeBatchDraft, parseBatchDraft, parseBatchResult,
  readBatchDraft, readBatchResult, revalidateBatchDraft, type BatchDraft,
} from './deploymentBatch';

vi.mock('./client', async importOriginal => ({
  ...await importOriginal<typeof import('./client')>(), get: vi.fn(), post: vi.fn(),
}));
const selections = [1, 2].map(n => ({ change_request_id: `cr${n}`, environment_id: 'env1', binding_id: `b${n}` }));
function fixture(): BatchDraft {
  return {
    schema_version: 'enterprise-batch-draft/v1', id: 'draft1', state: 'previewed', submission_supported: false,
    created_at: '2026-09-25T00:00:00Z', expires_at: '2026-09-25T00:05:00Z',
    preview: { schema_version: 'enterprise-deployment-batch-preview/v1', preview_digest: 'a'.repeat(64),
      batch_submission_supported: false, items: selections.map((selection, index) => ({
        schema_version: 'deployment-preview/v1', change_id: selection.change_request_id,
        environment_id: selection.environment_id, binding_id: selection.binding_id,
        policy_id: 'policy1', policy_name: 'Synthetic policy', policy_version: 1, enforcement_mode: 'block',
        environment_name: 'Fixture', target: `target${index}`, backend: 'fake', action: 'development_task',
        base_revision: null, preview_digest: String(index + 1).repeat(64),
      })),
    },
  };
}
function execution(draft = fixture()) {
  return { schema_version: 'enterprise-batch-execution/v1', reservation_id: 'reservation1', draft_id: draft.id,
    state: 'recorded', retry_executes: false, items: draft.preview.items.map((item, index) => ({
      schema_version: 'deployment-submission/v1', id: `submission${index}`, change_id: item.change_id,
      deployment_id: `deployment${index}`, state: 'recorded', deployment_status: 'sent',
      preview_digest: item.preview_digest, created_at: '2026-09-25T00:01:00Z',
    })),
  };
}
beforeEach(() => vi.resetAllMocks());

describe('batch draft contract', () => {
  it('rejects non-string draft state', () => {
    expect(() => parseBatchDraft({ ...fixture(), state: ['previewed'] })).toThrow();
  });
  it('matches selection independently of caller order; preserves server order and expired state', () => {
    expect(parseBatchDraft(fixture(), 'draft1', [...selections].reverse())).toEqual(fixture());
    expect(parseBatchDraft({ ...fixture(), state: 'expired' }).state).toBe('expired');
  });
  it('rejects wrong identity, extra fields, invalid time and changed capability', () => {
    for (const value of [null, [], { ...fixture(), id: 'other' }, { ...fixture(), tenant_id: 'other' },
      { ...fixture(), expires_at: 'invalid' }, { ...fixture(), expires_at: fixture().created_at },
      { ...fixture(), submission_supported: true }, { ...fixture(), state: '__proto__' }]) {
      expect(() => parseBatchDraft(value, 'draft1')).toThrow();
    }
  });
  it('rejects omitted, duplicated, substituted targets and extra nested data', () => {
    for (const mutate of [
      (d: BatchDraft) => { d.preview.items.pop(); },
      (d: BatchDraft) => { d.preview.items[1] = d.preview.items[0]; },
      (d: BatchDraft) => { d.preview.items[0].environment_id = 'other'; },
      (d: BatchDraft) => { d.preview.items[0].binding_id = 'other'; },
      (d: BatchDraft) => { d.preview.items[0].change_id = 'other'; },
      (d: BatchDraft) => { d.preview.items[0].target = d.preview.items[1].target; },
      (d: BatchDraft) => { Object.assign(d.preview.items[0], { raw_policy: {} }); },
      (d: BatchDraft) => { d.preview.preview_digest = 'invalid'; },
    ]) {
      const draft = fixture(); mutate(draft);
      expect(() => parseBatchDraft(draft, 'draft1', selections)).toThrow();
    }
  });
  it('validates size and duplicate bindings when restoring without local selections', () => {
    for (const items of [[], Array(21).fill(fixture().preview.items[0]),
      [fixture().preview.items[0], { ...fixture().preview.items[1], binding_id: 'b1' }]]) {
      expect(() => parseBatchDraft({ ...fixture(), preview: { ...fixture().preview, items } })).toThrow();
    }
  });
});

describe('batch result contract', () => {
  it('preserves sent, never promotes recorded to effective, normalizes readonly query', () => {
    const value = execution();
    expect(parseBatchResult(value, fixture(), 'execution').items[0].deployment_status).toBe('sent');
    const { reservation_id, retry_executes: _retry, ...rest } = value;
    expect(parseBatchResult({ ...rest, schema_version: 'enterprise-batch-reservation/v1',
      id: reservation_id, execution_supported: false }, fixture(), 'reservation'))
      .toEqual(parseBatchResult(value, fixture(), 'execution'));
  });
  it('requires unknown to dominate partial failure, and failure to dominate recorded', () => {
    const value = execution();
    value.items[1].state = 'needs_attention'; value.items[1].deployment_status = 'failed';
    expect(() => parseBatchResult(value, fixture(), 'execution')).toThrow();
    value.state = 'needs_attention';
    expect(parseBatchResult(value, fixture(), 'execution').state).toBe('needs_attention');
    value.items[0].state = 'unconfirmed'; value.items[0].deployment_status = 'pending';
    expect(() => parseBatchResult(value, fixture(), 'execution')).toThrow();
    value.state = 'unconfirmed';
    expect(parseBatchResult(value, fixture(), 'execution').state).toBe('unconfirmed');
  });
  it('rejects wrong batch, reordered results, duplicate ids and mismatched digests', () => {
    for (const mutate of [
      (v: ReturnType<typeof execution>) => { v.draft_id = 'other'; },
      (v: ReturnType<typeof execution>) => { v.items.reverse(); },
      (v: ReturnType<typeof execution>) => { v.items.pop(); },
      (v: ReturnType<typeof execution>) => { v.items[1].id = v.items[0].id; },
      (v: ReturnType<typeof execution>) => { v.items[1].deployment_id = v.items[0].deployment_id; },
      (v: ReturnType<typeof execution>) => { v.items[0].preview_digest = 'f'.repeat(64); },
      (v: ReturnType<typeof execution>) => { v.retry_executes = true; },
    ]) {
      const value = execution(); mutate(value);
      expect(() => parseBatchResult(value, fixture(), 'execution')).toThrow();
    }
  });
});

describe('explicit client operations', () => {
  it('creates only a draft with the original selections and caller key', async () => {
    vi.mocked(post).mockResolvedValue(fixture());
    expect(await createBatchDraft(selections, 'request-key')).toEqual(fixture());
    expect(post).toHaveBeenCalledExactlyOnceWith('/deployment-batch-drafts', {
      schema_version: 'enterprise-batch-draft-create/v1', request_key: 'request-key',
      items: selections.map(item => ({ schema_version: 'deployment-preview-request/v1', ...item })),
    }, { timeoutMs: 60000 });
  });
  it('rejects invalid selections before any request', async () => {
    for (const items of [[], [selections[0], selections[0]], Array(21).fill(selections[0])]) {
      await expect(createBatchDraft(items, 'key')).rejects.toThrow();
    }
    expect(post).not.toHaveBeenCalled();
  });
  it('restores by GET only and refuses mismatched draft identity', async () => {
    vi.mocked(get).mockResolvedValue(fixture());
    expect(await readBatchDraft('draft1')).toEqual(fixture());
    await expect(readBatchDraft('other')).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });
  it('revalidation does not execute or silently replace digest/expiry', async () => {
    vi.mocked(post).mockResolvedValue(fixture());
    expect(await revalidateBatchDraft(fixture())).toEqual(fixture());
    expect(vi.mocked(post).mock.calls[0][0]).toBe('/deployment-batch-drafts/draft1/revalidate');
    const changed = fixture(); changed.expires_at = '2026-09-25T00:06:00Z';
    vi.mocked(post).mockResolvedValue(changed);
    await expect(revalidateBatchDraft(fixture())).rejects.toThrow();
    changed.expires_at = fixture().expires_at; changed.preview.preview_digest = 'b'.repeat(64);
    await expect(revalidateBatchDraft(fixture())).rejects.toThrow();
  });
  it('requires explicit true, and sends only the execution contract fields', async () => {
    await expect(executeBatchDraft(fixture(), false as true)).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
    vi.mocked(post).mockResolvedValue(execution());
    await executeBatchDraft(fixture(), true);
    expect(post).toHaveBeenCalledExactlyOnceWith('/deployment-batch-drafts/draft1/execute', {
      schema_version: 'enterprise-batch-execute/v1', preview_digest: 'a'.repeat(64), confirm_execution: true,
    }, { timeoutMs: 60000 });
  });
  it('timeout propagates uncertainty without a second POST', async () => {
    const timeout = new ApiError(0, 'timeout'); vi.mocked(post).mockRejectedValue(timeout);
    await expect(executeBatchDraft(fixture(), true)).rejects.toBe(timeout);
    expect(post).toHaveBeenCalledTimes(1); expect(get).not.toHaveBeenCalled();
  });
  it('only the precise missing-reservation code yields null; access/identity failures remain errors', async () => {
    vi.mocked(get).mockRejectedValue(new ApiError(404, 'missing', 'batch_reservation_not_found'));
    expect(await readBatchResult(fixture())).toBeNull();
    for (const error of [new ApiError(404, 'missing', 'not_found'), new ApiError(403, 'denied'), new ApiError(502, 'down')]) {
      vi.mocked(get).mockRejectedValue(error);
      await expect(readBatchResult(fixture())).rejects.toBe(error);
    }
    expect(post).not.toHaveBeenCalled();
  });
});
