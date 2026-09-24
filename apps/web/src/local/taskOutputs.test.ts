import { describe, expect, it } from 'vitest';
import { parseTaskOutputs, parseTaskOutputContent } from './taskOutputs';
import type { RawContentRecord } from './rawTaskContentManagement';

const id = 'a'.repeat(64), snapshot = 'b'.repeat(64), ref = `sha256:${'c'.repeat(64)}`;
const record: RawContentRecord = { schema_version: 'local-raw-task-content-record/v1', status: 'active', record_id: `raw-${'d'.repeat(32)}`,
  task_ref: ref, kind: 'output', created_at: '2026-09-23T01:00:00Z', expires_at: '2026-09-23T02:00:00Z', plaintext_sha256: 'e'.repeat(64), plaintext_bytes: 128, omitted_secret_count: 0 };
const list = { schema_version: 'local-task-outputs/v1', activity_id: id, snapshot, status: 'ready', task_ref: ref, items: [record] };
const content = { schema_version: 'local-task-output-content/v1', activity_id: id, snapshot,
  content: { schema_version: 'local-raw-task-content-record-content/v1', contains_plaintext: true, record, fields: [{ path: '/result', value: '<script>untrusted</script>' }] } };
describe('runtime output response binding', () => {
  it('accepts exact authenticated metadata and plain text', () => {
    expect(parseTaskOutputs(list, id, snapshot, ref).items).toEqual([record]);
    expect(parseTaskOutputContent(content, id, snapshot, record).fields[0].value).toContain('<script>');
  });
  it('rejects stale, foreign, non-output and inconsistent states', () => {
    for (const patch of [{ activity_id: 'f'.repeat(64) }, { snapshot: 'f'.repeat(64) }, { task_ref: `sha256:${'f'.repeat(64)}` },
      { items: [{ ...record, kind: 'input' }] }, { status: 'disabled' }, { items: [record, record] }, { plaintext: 'unexpected' }]) {
      expect(() => parseTaskOutputs({ ...list, ...patch }, id, snapshot, ref)).toThrow();
    }
  });
  it('rejects content replacement, expired records and oversized aggregate text', () => {
    for (const patch of [{ activity_id: 'f'.repeat(64) }, { snapshot: 'f'.repeat(64) },
      { content: { ...content.content, record: { ...record, plaintext_sha256: 'f'.repeat(64) } } },
      { content: { ...content.content, record: { ...record, status: 'expired' } } },
      { content: { ...content.content, fields: [{ path: '/result', value: 'x'.repeat(129) }] } }]) {
      expect(() => parseTaskOutputContent({ ...content, ...patch }, id, snapshot, record)).toThrow();
    }
  });
});
