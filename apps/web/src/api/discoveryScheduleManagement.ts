import { get, post } from './client';

export const MANAGEMENT_VERSION = 'enterprise-discovery-schedule-management/v1';
const STATE_VERSION = 'enterprise-discovery-schedule-state/v1';
const SCHEDULE_ID = /^eds-[a-f0-9]{32}$/;
const DEVICE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/;
const UTC_Z = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;
const DIGEST = /^[a-f0-9]{64}$/;
const STATUSES = ['pending_confirmation', 'active', 'paused', 'revoked'] as const;

export type DiscoveryScheduleStatus = (typeof STATUSES)[number];

export interface DiscoveryScheduleItem {
  schedule_id: string;
  edge_agent_id: string;
  status: DiscoveryScheduleStatus;
  revision: number;
  starts_at: string;
  expires_at: string;
  interval_seconds: number;
  max_runs: number;
  reserved_runs: number;
  last_reserved_slot: number | null;
  created_at: string;
}

export interface DiscoverySchedulePage {
  schema_version: typeof MANAGEMENT_VERSION;
  environment_id: string;
  evaluated_at: string;
  can_revoke: boolean;
  items: DiscoveryScheduleItem[];
  next_cursor: string | null;
}

export interface DiscoveryScheduleState {
  schema_version: typeof STATE_VERSION;
  schedule_id: string;
  status: DiscoveryScheduleStatus;
  revision: number;
  intent_digest: string;
}

const itemFields = ['schedule_id', 'edge_agent_id', 'status', 'revision', 'starts_at', 'expires_at',
  'interval_seconds', 'max_runs', 'reserved_runs', 'last_reserved_slot', 'created_at'];
const pageFields = ['schema_version', 'environment_id', 'evaluated_at', 'can_revoke', 'items', 'next_cursor'];
const stateFields = ['schema_version', 'schedule_id', 'status', 'revision', 'intent_digest'];

function validEnvironmentId(value: string): boolean {
  return typeof value === 'string' && value.length <= 64 && DEVICE_ID.test(value);
}
function nonNegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function utcZ(value: unknown): value is string {
  return typeof value === 'string' && UTC_Z.test(value) && !value.startsWith('0000-')
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19);
}
function knownStatus(value: unknown): value is DiscoveryScheduleStatus {
  return typeof value === 'string' && (STATUSES as readonly string[]).includes(value);
}

export function parseDiscoveryScheduleItem(value: unknown): DiscoveryScheduleItem {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('周期发现计划条目待核对');
  const row = value as Record<string, unknown>;
  if (Object.keys(row).length !== itemFields.length || !itemFields.every(field => Object.hasOwn(row, field))
    || typeof row.schedule_id !== 'string' || !SCHEDULE_ID.test(row.schedule_id)
    || typeof row.edge_agent_id !== 'string' || !validEnvironmentId(row.edge_agent_id)
    || !knownStatus(row.status) || !nonNegative(row.revision)
    || !utcZ(row.starts_at) || !utcZ(row.expires_at)
    || !nonNegative(row.interval_seconds) || !nonNegative(row.max_runs) || !nonNegative(row.reserved_runs)
    || row.reserved_runs > row.max_runs
    || (row.last_reserved_slot !== null && !nonNegative(row.last_reserved_slot))
    || !utcZ(row.created_at)
    || Date.parse(row.starts_at) >= Date.parse(row.expires_at)) {
    throw new Error('周期发现计划条目待核对');
  }
  return row as unknown as DiscoveryScheduleItem;
}

export function parseDiscoverySchedulePage(value: unknown, environmentId: string): DiscoverySchedulePage {
  if (!validEnvironmentId(environmentId)) throw new Error('环境标识无效');
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('周期发现计划列表待核对');
  const row = value as Record<string, unknown>;
  if (Object.keys(row).length !== pageFields.length || !pageFields.every(field => Object.hasOwn(row, field))
    || row.schema_version !== MANAGEMENT_VERSION
    || row.environment_id !== environmentId
    || !utcZ(row.evaluated_at) || typeof row.can_revoke !== 'boolean'
    || !Array.isArray(row.items) || row.items.length > 100
    || !(row.next_cursor === null || typeof row.next_cursor === 'string' && SCHEDULE_ID.test(row.next_cursor))) {
    throw new Error('周期发现计划列表待核对');
  }
  const items = row.items.map(parseDiscoveryScheduleItem);
  if (items.some((item, index) => index > 0 && items[index - 1].schedule_id >= item.schedule_id)) {
    throw new Error('周期发现计划列表待核对');
  }
  if (row.next_cursor !== null && (items.length === 0 || row.next_cursor !== items[items.length - 1].schedule_id)) {
    throw new Error('周期发现计划列表待核对');
  }
  return {
    schema_version: MANAGEMENT_VERSION, environment_id: environmentId,
    evaluated_at: row.evaluated_at as string, can_revoke: row.can_revoke as boolean,
    items, next_cursor: row.next_cursor as string | null,
  };
}

export async function listDiscoverySchedules(environmentId: string, cursor?: string | null) {
  if (!validEnvironmentId(environmentId)) throw new Error('环境标识无效');
  if (cursor !== undefined && cursor !== null && !SCHEDULE_ID.test(cursor)) throw new Error('分页游标无效');
  const page = parseDiscoverySchedulePage(await get<unknown>('/environments/' + encodeURIComponent(environmentId)
    + '/discovery-schedules', { query: cursor ? { cursor } : undefined }), environmentId);
  if (cursor && page.items.some(item => item.schedule_id <= cursor)) throw new Error('周期发现计划分页未前进');
  return page;
}

/** One explicit write, never an automatic retry; the response must match the requested plan. */
export async function revokeDiscoverySchedule(
  environmentId: string, scheduleId: string, expectedRevision: number,
): Promise<DiscoveryScheduleState> {
  if (!validEnvironmentId(environmentId) || !SCHEDULE_ID.test(scheduleId)) throw new Error('环境或计划标识无效');
  if (!nonNegative(expectedRevision)) throw new Error('计划版本无效');
  const value = await post<unknown>('/environments/' + encodeURIComponent(environmentId)
    + '/discovery-schedules/' + encodeURIComponent(scheduleId) + '/revoke', { expected_revision: expectedRevision });
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('撤销结果待核对');
  const row = value as Record<string, unknown>;
  if (Object.keys(row).length !== stateFields.length || !stateFields.every(field => Object.hasOwn(row, field))
    || row.schema_version !== STATE_VERSION || row.schedule_id !== scheduleId || row.status !== 'revoked'
    || !nonNegative(row.revision) || row.revision < expectedRevision
    || typeof row.intent_digest !== 'string' || !DIGEST.test(row.intent_digest)) {
    throw new Error('撤销结果待核对');
  }
  return row as unknown as DiscoveryScheduleState;
}
