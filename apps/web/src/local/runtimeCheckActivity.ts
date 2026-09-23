import { isTaskActivityPage, type TaskActivityItem, type TaskActivityPage } from './taskActivities';
import type { RuntimeCheckResult } from './types';

export interface RuntimeCheckActivity {
  schema_version: 'local-runtime-check-activity/v1';
  check_id: string;
  instance_id: string;
  snapshot: string;
  prefix_valid: true;
  history_integrity: 'verified' | 'unknown';
  activity: TaskActivityItem;
}

export function isRuntimeCheckActivity(value: unknown, result: RuntimeCheckResult): value is RuntimeCheckActivity {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const data = value as RuntimeCheckActivity;
  if (data.schema_version !== 'local-runtime-check-activity/v1' || data.check_id !== result.check_id
    || data.instance_id !== result.instance_id || !['verified', 'unknown'].includes(data.history_integrity)
    || result.receipt_ids.length === 0) return false;
  const page: TaskActivityPage = {
    schema_version: 'local-task-activities/v1', snapshot: data.snapshot, view: 'tasks', offset: 0,
    total: 1, next_offset: null, prefix_valid: data.prefix_valid, history_integrity: data.history_integrity,
    evidence_freshness: 'unknown', items: [data.activity],
  };
  return isTaskActivityPage(page, 'tasks', 0) && data.activity.binding?.platform === 'hermes'
    && data.activity.receipt_count >= result.receipt_ids.length;
}

export function runtimeCheckActivityURL(data: RuntimeCheckActivity): string {
  const binding = data.activity.binding!;
  const params = new URLSearchParams({ view: 'tasks', snapshot: data.snapshot, platform: binding.platform,
    agent_id: binding.agent_id, session_id: binding.session_id, task_id: binding.task_id });
  return `/activities/${encodeURIComponent(data.activity.activity_id)}?${params}`;
}
