import { isRawContentRecordContent, readRawContentRecords, type RawContentRecord, type RawContentRecordContent } from './rawTaskContentManagement';

export interface TaskOutputs {
  schema_version: 'local-task-outputs/v1'; activity_id: string; snapshot: string;
  status: 'ready' | 'disabled' | 'unattributed'; task_ref: string | null; items: RawContentRecord[];
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => k in v);
export function parseTaskOutputs(value: unknown, id: string, snapshot: string, taskRef: string): TaskOutputs {
  if (!object(value) || !exact(value, ['schema_version', 'activity_id', 'snapshot', 'status', 'task_ref', 'items']) ||
    value.schema_version !== 'local-task-outputs/v1' || value.activity_id !== id || value.snapshot !== snapshot ||
    value.task_ref !== taskRef || !['ready', 'disabled', 'unattributed'].includes(String(value.status))) throw new Error('输出目录响应与当前运行不一致');
  const items = readRawContentRecords({ schema_version: 'local-raw-task-content-records/v1', items: value.items }, taskRef);
  if (!items || items.some(r => r.kind !== 'output') || (value.status !== 'ready' && items.length !== 0)) throw new Error('输出目录响应不完整');
  return value as unknown as TaskOutputs;
}
export function parseTaskOutputContent(value: unknown, id: string, snapshot: string, record: RawContentRecord): RawContentRecordContent {
  if (!object(value) || !exact(value, ['schema_version', 'activity_id', 'snapshot', 'content']) ||
    value.schema_version !== 'local-task-output-content/v1' || value.activity_id !== id || value.snapshot !== snapshot ||
    record.kind !== 'output' || !isRawContentRecordContent(value.content, record)) throw new Error('输出内容响应与所选记录不一致');
  if (value.content.fields.reduce((n, f) => n + new TextEncoder().encode(f.value).length, 0) > record.plaintext_bytes) throw new Error('输出内容超出记录大小');
  return value.content;
}
