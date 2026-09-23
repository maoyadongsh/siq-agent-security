import { isTaskActivityPage, validActivityFilter, type ActivityFilters, type ActivityView, type TaskActivityItem, type TaskActivityPage } from './taskActivities';

export const activityFilterNames = ['platform', 'agent_id', 'session_id', 'task_id', 'q', 'from', 'to', 'action'] as const;
export const decisionNames = ['allow', 'deny', 'hold', 'redact', 'other'] as const;
export interface ActivityQueryFilters extends ActivityFilters { from: string; to: string; action: string }
export interface ActivityQueryItem extends TaskActivityItem { last_recorded_at: string | null; decisions: Record<typeof decisionNames[number], number> }
export interface ActivityQueryPage extends Omit<TaskActivityPage, 'schema_version' | 'items'> {
  schema_version: 'local-task-activity-query/v1'; filters: ActivityQueryFilters; items: ActivityQueryItem[];
}
export const emptyActivityFilters: ActivityQueryFilters = { platform: '', agent_id: '', session_id: '', task_id: '', q: '', from: '', to: '', action: '' };
export const readActivityFilters = (params: URLSearchParams): ActivityQueryFilters => Object.fromEntries(activityFilterNames.map((name) => {
  const value = params.get(name) ?? '';
  return [name, validActivityFilter(value) ? value : ''];
})) as unknown as ActivityQueryFilters;
export const activityQueryParams = (view: ActivityView, filters: ActivityQueryFilters, extra: Record<string, string> = {}) => {
  const params = new URLSearchParams({ view });
  for (const name of activityFilterNames) if (filters[name]) params.set(name, filters[name]);
  for (const [name, value] of Object.entries(extra)) if (value) params.set(name, value);
  return params;
};
export function isActivityQueryPage(value: unknown, view: ActivityView, offset: number, filters: ActivityQueryFilters, snapshot?: string): value is ActivityQueryPage {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const data = value as ActivityQueryPage;
  if (data.schema_version !== 'local-task-activity-query/v1' || !data.filters
    || activityFilterNames.some((name) => data.filters[name] !== filters[name])
    || !isTaskActivityPage({ ...data, schema_version: 'local-task-activities/v1' }, view, offset, snapshot)) return false;
  let last = Infinity;
  return data.items.every((item) => {
    if (item.last_seq >= last || (item.last_recorded_at !== null && (typeof item.last_recorded_at !== 'string' || !Number.isFinite(Date.parse(item.last_recorded_at))))
      || !item.decisions || Object.keys(item.decisions).length !== decisionNames.length) return false;
    last = item.last_seq;
    let sum = 0;
    for (const name of decisionNames) {
      const count = item.decisions[name];
      if (!Number.isSafeInteger(count) || count < 0) return false;
      sum += count;
    }
    return sum <= item.receipt_count;
  });
}
export function localDateTime(value: string): string {
  if (!value) return '';
  const at = new Date(value);
  if (!Number.isFinite(at.getTime())) return '';
  return new Date(at.getTime() - at.getTimezoneOffset() * 60000).toISOString().slice(0, -1);
}
