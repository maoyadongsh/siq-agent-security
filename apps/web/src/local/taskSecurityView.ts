import { isActivityCompletion, type CompletionResult, type CompletionStatus } from './taskCompletion';
import { isTaskActivityPage, type ActivityView, type TaskActivityItem } from './taskActivities';

export type SecurityAuthorizationStatus = 'authorized' | 'denied' | 'pending' | 'mixed' | 'unknown';
export type SecurityDestinationStatus = 'observed' | 'partial' | 'unknown';

export interface TaskSecurityView {
  schema_version: 'local-task-security-view/v1';
  snapshot: string;
  evaluated_at: string;
  activity: TaskActivityItem;
  business_object: {
    status: 'verified' | 'referenced' | 'unknown';
    object_type: 'task';
    task_id: string | null;
    intent_id: string | null;
    contract_status: 'verified' | 'missing' | 'unknown' | 'unattributed';
    display_label_status: 'unavailable';
  };
  run_mode: {
    platform: string | null;
    enforcement_modes: Array<'block' | 'warn' | 'audit_only'>;
    mode_status: 'consistent' | 'mixed' | 'unknown';
    model_keys: string[];
    model_status: 'consistent' | 'mixed' | 'unknown';
    execution_context: 'sandbox_bound' | 'mixed' | 'unrecorded';
    sandbox_bound_receipts: number;
  };
  data_destinations: {
    status: SecurityDestinationStatus;
    destinations: Array<{ domain: 'filesystem' | 'network' | 'message'; resource_ref: string; effects: string[]; receipt_count: number }>;
    unresolved_receipt_count: number;
    plaintext_exposed: false;
  };
  authorization: {
    status: SecurityAuthorizationStatus;
    intent_binding: 'bound' | 'unknown';
    decisions: { authorized: number; denied: number; pending: number; unknown: number };
    matched_grant_count: number;
  };
  actual_result: {
    status: CompletionStatus;
    evaluation_status: 'evaluated' | 'attribution_unknown' | 'intent_missing';
    reason_code: string;
    result: CompletionResult | null;
  };
  release_assurance: { status: 'not_evaluated'; reason_code: 'native_candidate_evidence_not_connected' };
  evidence_integrity: { prefix_valid: true; history_integrity: 'verified' | 'unknown' | 'failed'; evidence_freshness: 'unknown' };
}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const integer = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const digest = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const orderedUnique = (values: unknown[]): boolean => values.every(text) && new Set(values).size === values.length && values.every((value, index) => index === 0 || String(values[index - 1]).localeCompare(String(value)) < 0);

function sameActivity(value: unknown, activity: TaskActivityItem, view: ActivityView, snapshot: string): value is TaskActivityItem {
  const summary = { schema_version: 'local-task-activities/v1', view, offset: 0, total: 1, next_offset: null, snapshot,
    prefix_valid: true, history_integrity: 'unknown', evidence_freshness: 'unknown', items: [value] };
  if (!isTaskActivityPage(summary, view, 0, snapshot, 1)) return false;
  const got = summary.items[0];
  if (got.activity_id !== activity.activity_id || got.attribution !== activity.attribution || got.receipt_count !== activity.receipt_count ||
      got.first_seq !== activity.first_seq || got.last_seq !== activity.last_seq) return false;
  for (const field of ['chain_id', 'platform', 'session_id', 'agent_id', 'task_id', 'intent_id', 'intent_digest'] as const) {
    if (got.binding?.[field] !== activity.binding?.[field]) return false;
  }
  return true;
}

function validAuthorization(value: unknown, activity: TaskActivityItem): boolean {
  if (!object(value) || !['authorized', 'denied', 'pending', 'mixed', 'unknown'].includes(String(value.status)) ||
      value.intent_binding !== (activity.binding ? 'bound' : 'unknown') || !object(value.decisions) || !integer(value.matched_grant_count)) return false;
  const counts = value.decisions;
  if (!integer(counts.authorized) || !integer(counts.denied) || !integer(counts.pending) || !integer(counts.unknown)) return false;
  const values = [counts.authorized, counts.denied, counts.pending, counts.unknown] as number[];
  if (values.reduce((sum, count) => sum + count, 0) < 1 || values.reduce((sum, count) => sum + count, 0) > activity.receipt_count || value.matched_grant_count > activity.receipt_count) return false;
  const populated = values.filter((count) => count > 0).length;
  const expected = populated > 1 ? 'mixed' : counts.authorized ? 'authorized' : counts.denied ? 'denied' : counts.pending ? 'pending' : 'unknown';
  return value.status === expected;
}

function validDestinations(value: unknown, activity: TaskActivityItem): boolean {
  if (!object(value) || !['observed', 'partial', 'unknown'].includes(String(value.status)) || value.plaintext_exposed !== false ||
      !integer(value.unresolved_receipt_count) || value.unresolved_receipt_count > activity.receipt_count || !Array.isArray(value.destinations) || value.destinations.length > 1024) return false;
  const keys: string[] = [];
  for (const item of value.destinations) {
    if (!object(item) || !['filesystem', 'network', 'message'].includes(String(item.domain)) || !digest(item.resource_ref) || !integer(item.receipt_count) || item.receipt_count < 1 ||
        item.receipt_count > activity.receipt_count || !Array.isArray(item.effects) || !orderedUnique(item.effects) || 'value' in item || 'path' in item || 'host' in item || 'recipient' in item) return false;
    keys.push(`${item.domain}:${item.resource_ref}`);
  }
  if (new Set(keys).size !== keys.length || !orderedUnique(keys)) return false;
  if (value.destinations.length === 0) return value.status === 'unknown';
  return value.status === (value.unresolved_receipt_count > 0 ? 'partial' : 'observed');
}

export function isTaskSecurityView(value: unknown, activity: TaskActivityItem, view: ActivityView, snapshot: string): value is TaskSecurityView {
  if (!object(value) || value.schema_version !== 'local-task-security-view/v1' || value.snapshot !== snapshot || !text(value.evaluated_at) ||
      !Number.isFinite(Date.parse(value.evaluated_at)) || !sameActivity(value.activity, activity, view, snapshot) || !object(value.business_object) ||
      !object(value.run_mode) || !object(value.actual_result) || !object(value.release_assurance) || !object(value.evidence_integrity)) return false;
  const business = value.business_object;
  if (business.object_type !== 'task' || business.display_label_status !== 'unavailable') return false;
  if (activity.binding) {
    if (business.task_id !== activity.binding.task_id || business.intent_id !== activity.binding.intent_id ||
        !['verified', 'missing', 'unknown'].includes(String(business.contract_status))) return false;
    const expected = business.contract_status === 'verified' ? 'verified' : 'referenced';
    if (business.status !== expected) return false;
  } else if (business.status !== 'unknown' || business.task_id !== null || business.intent_id !== null || business.contract_status !== 'unattributed') return false;

  const run = value.run_mode;
  if (run.platform !== (activity.binding?.platform ?? run.platform) || (run.platform !== null && !text(run.platform)) || !Array.isArray(run.enforcement_modes) ||
      run.enforcement_modes.some((mode) => !['block', 'warn', 'audit_only'].includes(String(mode))) || !orderedUnique(run.enforcement_modes) ||
      !Array.isArray(run.model_keys) || run.model_keys.length > 64 || !orderedUnique(run.model_keys) || run.model_keys.some((model) => new TextEncoder().encode(model).length > 256 || /[\u0000-\u001f\u007f-\u009f]/.test(model)) ||
      !['consistent', 'mixed', 'unknown'].includes(String(run.model_status)) ||
      !['consistent', 'mixed', 'unknown'].includes(String(run.mode_status)) || !['sandbox_bound', 'mixed', 'unrecorded'].includes(String(run.execution_context)) ||
      !integer(run.sandbox_bound_receipts) || run.sandbox_bound_receipts > activity.receipt_count) return false;
  if (run.enforcement_modes.length === 0 ? run.mode_status !== 'unknown' : run.enforcement_modes.length === 1
      ? !['consistent', 'mixed'].includes(String(run.mode_status)) : run.mode_status !== 'mixed') return false;
  if (run.model_keys.length === 0 ? run.model_status !== 'unknown' : run.model_keys.length === 1
      ? !['consistent', 'mixed'].includes(String(run.model_status)) : run.model_status !== 'mixed') return false;
  const expectedContext = run.sandbox_bound_receipts === 0 ? 'unrecorded' : run.sandbox_bound_receipts === activity.receipt_count ? 'sandbox_bound' : 'mixed';
  if (run.execution_context !== expectedContext) return false;
  if (!validDestinations(value.data_destinations, activity) || !validAuthorization(value.authorization, activity)) return false;

  const actual = value.actual_result;
  if (!['verified', 'incomplete', 'conflicting', 'unknown'].includes(String(actual.status)) ||
      !['evaluated', 'attribution_unknown', 'intent_missing'].includes(String(actual.evaluation_status)) || !text(actual.reason_code)) return false;
  const completion = { schema_version: 'local-task-activity-completion/v1', snapshot, evaluated_at: value.evaluated_at,
    activity: value.activity, reason_code: actual.evaluation_status, result: actual.result };
  if (!isActivityCompletion(completion, activity, snapshot, view)) return false;
  if (completion.result ? (actual.status !== completion.result.status || actual.reason_code !== completion.result.reason_code) : (actual.status !== 'unknown' || actual.reason_code !== actual.evaluation_status)) return false;

  const release = value.release_assurance;
  if (release.status !== 'not_evaluated' || release.reason_code !== 'native_candidate_evidence_not_connected') return false;
  const integrity = value.evidence_integrity;
  return integrity.prefix_valid === true && ['verified', 'unknown', 'failed'].includes(String(integrity.history_integrity)) && integrity.evidence_freshness === 'unknown';
}

export const authorizationLabel: Record<SecurityAuthorizationStatus, string> = {
  authorized: '已授权动作', denied: '已拒绝动作', pending: '有需批准裁决', mixed: '授权状态混合', unknown: '授权状态未知',
};
export const destinationStatusLabel: Record<SecurityDestinationStatus, string> = {
  observed: '去向引用已记录', partial: '部分去向未知', unknown: '去向未知',
};
