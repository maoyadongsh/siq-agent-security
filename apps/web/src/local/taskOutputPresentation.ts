import type { RawContentRecordContent } from './rawTaskContentManagement';

export function fileToolOutput(platform: string, fields: RawContentRecordContent['fields']): { text: string; truncated: boolean } | undefined {
  if (platform === 'hermes') return hermesFileOutput(platform, fields);
  if (platform !== 'openclaw' || fields.length !== 5) return;
  const paths = ['/tool/name', '/tool/result/content/0/type', '/tool/result/content/0/text',
    '/tool/result/details/kind', '/tool/result/details/content'];
  const values = new Map(fields.map(field => [field.path, field.value]));
  if (values.size !== paths.length || !paths.every(path => values.has(path)) || values.get('/tool/name') !== 'read') return;
  try {
    const decoded = paths.slice(1).map(path => {
      const value = values.get(path)!;
      if (value.length > 65536) throw new Error('display budget');
      return JSON.parse(value) as unknown;
    });
    const [type, text, kind, copy] = decoded;
    // Both native carriers must agree; otherwise show all captured fields.
    if (type !== 'text' || kind !== 'text' || typeof text !== 'string' || copy !== text) return;
    return { text, truncated: false };
  } catch { return; }
}

// A display projection of the known Hermes text-file response. Unknown shapes
// retain every captured field; this must never become a tool-status authority.
export function hermesFileOutput(platform: string, fields: RawContentRecordContent['fields']): { text: string; truncated: boolean } | undefined {
  if (platform !== 'hermes' || fields.length !== 2) return;
  const tools = fields.filter(field => field.path === '/tool/name');
  const results = fields.filter(field => field.path === '/tool/result');
  if (tools.length !== 1 || tools[0].value !== 'read_file' || results.length !== 1 || results[0].value.length > 65536) return;
  try {
    let parsed: unknown = JSON.parse(results[0].value);
    if (typeof parsed === 'string') parsed = JSON.parse(parsed);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return;
    const value = parsed as Record<string, unknown>;
    const keys = ['content', 'total_lines', 'file_size', 'truncated', 'is_binary', 'is_image'];
    if (Object.keys(value).length !== keys.length || !keys.every(key => Object.hasOwn(value, key)) ||
        typeof value.content !== 'string' || typeof value.truncated !== 'boolean' ||
        value.is_binary !== false || value.is_image !== false ||
        !Number.isSafeInteger(value.total_lines) || (value.total_lines as number) < 0 ||
        !Number.isSafeInteger(value.file_size) || (value.file_size as number) < 0) return;
    return { text: value.content, truncated: value.truncated };
  } catch { return; }
}
