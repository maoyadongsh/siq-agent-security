/** Explicit batch protocol. No automatic execution retry or browser persistence. */
import { ApiError, get, post } from './client';
import { parseDeploymentPreview, type DeploymentPreview, type DeploymentSelection } from './deploymentPreview';
import { parseDeploymentSubmission, type DeploymentSubmission } from './deploymentSubmission';

type ObjectValue = Record<string, unknown>;
const object = (v: unknown): v is ObjectValue => v !== null && typeof v === 'object' && !Array.isArray(v);
const id = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 64;
const digest = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const timestamp = (v: unknown): v is string => typeof v === 'string' && v.endsWith('Z') && Number.isFinite(Date.parse(v));
function requireValue(ok: unknown): asserts ok {
  if (!ok) throw new Error('批次响应不完整或与所选目标不匹配，请重新核对；不要自动重试执行。');
}
function exact(v: unknown, keys: string[]): asserts v is ObjectValue {
  requireValue(object(v) && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k)));
}

export interface BatchDraft {
  schema_version: 'enterprise-batch-draft/v1';
  id: string;
  preview: {
    schema_version: 'enterprise-deployment-batch-preview/v1';
    items: DeploymentPreview[];
    preview_digest: string;
    batch_submission_supported: false;
  };
  created_at: string;
  expires_at: string;
  state: 'previewed' | 'expired';
  submission_supported: false;
}
export interface BatchResult {
  reservation_id: string;
  draft_id: string;
  state: 'unconfirmed' | 'recorded' | 'needs_attention';
  items: DeploymentSubmission[];
}

function validateSelections(items: readonly DeploymentSelection[]) {
  requireValue(items.length >= 1 && items.length <= 20);
  for (const item of items) {
    exact(item, ['change_request_id', 'environment_id', 'binding_id']);
    requireValue(id(item.change_request_id) && id(item.environment_id) && id(item.binding_id));
  }
  requireValue(new Set(items.map(v => v.change_request_id)).size === items.length);
  requireValue(new Set(items.map(v => v.binding_id)).size === items.length);
}

export function parseBatchDraft(value: unknown, expectedId?: string, selections?: readonly DeploymentSelection[]): BatchDraft {
  exact(value, ['schema_version', 'id', 'preview', 'created_at', 'expires_at', 'state', 'submission_supported']);
  requireValue(value.schema_version === 'enterprise-batch-draft/v1' && id(value.id));
  requireValue(expectedId === undefined || value.id === expectedId);
  requireValue(value.submission_supported === false && typeof value.state === 'string' && ['previewed', 'expired'].includes(value.state));
  requireValue(timestamp(value.created_at) && timestamp(value.expires_at));
  requireValue(Date.parse(value.expires_at) > Date.parse(value.created_at));
  const preview = value.preview;
  exact(preview, ['schema_version', 'items', 'preview_digest', 'batch_submission_supported']);
  requireValue(preview.schema_version === 'enterprise-deployment-batch-preview/v1');
  requireValue(digest(preview.preview_digest) && preview.batch_submission_supported === false);
  requireValue(Array.isArray(preview.items));
  const restored = preview.items.map((item: unknown): DeploymentSelection => {
    requireValue(object(item));
    requireValue(id(item.change_id) && id(item.environment_id) && id(item.binding_id));
    return { change_request_id: item.change_id, environment_id: item.environment_id, binding_id: item.binding_id };
  });
  validateSelections(restored);
  const expected = selections ?? restored;
  validateSelections(expected);
  requireValue(expected.length === restored.length);
  const byChange = new Map(expected.map(item => [item.change_request_id, item]));
  const items = preview.items.map((item, index) => {
    const selection = byChange.get(restored[index].change_request_id);
    requireValue(selection);
    return parseDeploymentPreview(item, selection);
  });
  requireValue(new Set(items.map(item => JSON.stringify([item.backend, item.target]))).size === items.length);
  return { ...value, preview: { ...preview, items } } as unknown as BatchDraft;
}

export function parseBatchResult(value: unknown, draft: BatchDraft, kind: 'execution' | 'reservation'): BatchResult {
  const execution = kind === 'execution';
  exact(value, ['schema_version', execution ? 'reservation_id' : 'id', 'draft_id', 'state', 'items',
    execution ? 'retry_executes' : 'execution_supported']);
  requireValue(value.schema_version === (execution ? 'enterprise-batch-execution/v1' : 'enterprise-batch-reservation/v1'));
  const reservationId = execution ? value.reservation_id : value.id;
  requireValue(id(reservationId) && value.draft_id === draft.id);
  requireValue((execution ? value.retry_executes : value.execution_supported) === false);
  requireValue(Array.isArray(value.items) && value.items.length === draft.preview.items.length);
  const items = value.items.map((item, index) => {
    const expected = draft.preview.items[index];
    const parsed = parseDeploymentSubmission(item, expected.change_id);
    requireValue(parsed.preview_digest === expected.preview_digest);
    return parsed;
  });
  requireValue(new Set(items.map(item => item.id)).size === items.length);
  requireValue(new Set(items.map(item => item.deployment_id)).size === items.length);
  const state = items.some(item => item.state === 'unconfirmed') ? 'unconfirmed'
    : items.some(item => item.state === 'needs_attention') ? 'needs_attention' : 'recorded';
  requireValue(value.state === state);
  return { reservation_id: reservationId, draft_id: draft.id, state, items };
}

export async function createBatchDraft(selections: readonly DeploymentSelection[], requestKey: string) {
  validateSelections(selections);
  const value = await post<unknown>('/deployment-batch-drafts', {
    schema_version: 'enterprise-batch-draft-create/v1', request_key: requestKey,
    items: selections.map(item => ({ schema_version: 'deployment-preview-request/v1', ...item })),
  }, { timeoutMs: 60000 });
  return parseBatchDraft(value, undefined, selections);
}
export async function readBatchDraft(draftId: string) {
  requireValue(id(draftId));
  return parseBatchDraft(await get<unknown>(`/deployment-batch-drafts/${encodeURIComponent(draftId)}`), draftId);
}
export async function revalidateBatchDraft(draft: BatchDraft) {
  const value = await post<unknown>(`/deployment-batch-drafts/${encodeURIComponent(draft.id)}/revalidate`, {
    schema_version: 'enterprise-batch-draft-revalidate/v1', preview_digest: draft.preview.preview_digest,
  }, { timeoutMs: 60000 });
  const parsed = parseBatchDraft(value, draft.id, draft.preview.items.map(item => ({
    change_request_id: item.change_id, environment_id: item.environment_id, binding_id: item.binding_id,
  })));
  requireValue(parsed.preview.preview_digest === draft.preview.preview_digest);
  requireValue(parsed.created_at === draft.created_at && parsed.expires_at === draft.expires_at);
  return parsed;
}
export async function executeBatchDraft(draft: BatchDraft, confirmExecution: true) {
  requireValue(confirmExecution === true);
  const value = await post<unknown>(`/deployment-batch-drafts/${encodeURIComponent(draft.id)}/execute`, {
    schema_version: 'enterprise-batch-execute/v1', preview_digest: draft.preview.preview_digest, confirm_execution: true,
  }, { timeoutMs: 60000 });
  return parseBatchResult(value, draft, 'execution');
}
export async function readBatchResult(draft: BatchDraft): Promise<BatchResult | null> {
  try {
    return parseBatchResult(await get<unknown>(`/deployment-batch-drafts/${encodeURIComponent(draft.id)}/reservation`), draft, 'reservation');
  } catch (error) {
    if (error instanceof ApiError && error.status === 404 && error.code === 'batch_reservation_not_found') return null;
    throw error;
  }
}
