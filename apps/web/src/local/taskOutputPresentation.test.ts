import { describe, expect, it } from 'vitest';
import { fileToolOutput, hermesFileOutput } from './taskOutputPresentation';

const response = { content: '1|正文\n2|<script>alert(1)</script>', total_lines: 2, file_size: 42, truncated: false, is_binary: false, is_image: false };
const fields = (value: string) => [{ path: '/tool/name', value: 'read_file' }, { path: '/tool/result', value }];

describe('Hermes file output display projection', () => {
  it('shows text without interpreting markup or changing the original fields', () => {
    const input = fields(JSON.stringify(JSON.stringify(response)));
    const original = JSON.stringify(input);
    expect(hermesFileOutput('hermes', input)).toEqual({ text: response.content, truncated: false });
    expect(JSON.stringify(input)).toBe(original);
    expect(hermesFileOutput('hermes', fields(JSON.stringify({ ...response, truncated: true })))).toEqual({ text: response.content, truncated: true });
  });
  it('does not hide unexpected error, warning, binary or malformed response fields', () => {
    for (const value of [{ ...response, error: 'failed' }, { ...response, warning: 'partial' },
      { ...response, is_binary: true }, { ...response, is_image: true }, { ...response, truncated: 'false' },
      { ...response, total_lines: -1 }, { ...response, file_size: 1.2 }, { content: 'only text' }, null, [response]]) {
      expect(hermesFileOutput('hermes', fields(JSON.stringify(value)))).toBeUndefined();
    }
    for (const value of ['not JSON', '{', JSON.stringify(JSON.stringify(JSON.stringify(response))), 'x'.repeat(65537)]) {
      expect(hermesFileOutput('hermes', fields(value))).toBeUndefined();
    }
  });
  it('requires the exact platform, tool and unique captured fields', () => {
    const input = fields(JSON.stringify(response));
    expect(hermesFileOutput('openclaw', input)).toBeUndefined();
    expect(hermesFileOutput('hermes', [{ ...input[0], value: 'terminal' }, input[1]])).toBeUndefined();
    expect(hermesFileOutput('hermes', [...input, { path: '/other', value: 'important' }])).toBeUndefined();
    expect(hermesFileOutput('hermes', [input[1], input[1]])).toBeUndefined();
    expect(hermesFileOutput('hermes', [{ ...input[0], path: '/tool/name/extra' }, input[1]])).toBeUndefined();
  });
});

describe('OpenClaw native read output display projection', () => {
  const text = '正文\n<script>alert(1)</script>';
  const input = [
    { path: '/tool/name', value: 'read' },
    { path: '/tool/result/content/0/type', value: '"text"' },
    { path: '/tool/result/content/0/text', value: JSON.stringify(text) },
    { path: '/tool/result/details/kind', value: '"text"' },
    { path: '/tool/result/details/content', value: JSON.stringify(text) },
  ];
  it('shows matching native text once and preserves captured fields', () => {
    const original = JSON.stringify(input);
    expect(fileToolOutput('openclaw', input)).toEqual({ text, truncated: false });
    expect(JSON.stringify(input)).toBe(original);
    expect(fileToolOutput('hermes', fields(JSON.stringify(response)))).toEqual({ text: response.content, truncated: false });
  });
  it('retains mismatched, malformed, non-text and oversized carriers in the original view', () => {
    for (const [index, value] of [[4, '"different"'], [4, 'null'], [3, '"image"'], [1, '"image"'],
      [2, '{}'], [2, 'not JSON'], [2, '"' + 'x'.repeat(65536) + '"'], [0, 'exec']] as const) {
      expect(fileToolOutput('openclaw', input.map((field, i) => i === index ? { ...field, value } : field))).toBeUndefined();
    }
  });
  it('never hides extra errors or truncation fields or accepts duplicate paths and foreign platforms', () => {
    for (const path of ['/tool/result/error', '/tool/result/details/truncated', '/tool/result/content/1/text']) {
      expect(fileToolOutput('openclaw', [...input, { path, value: 'true' }])).toBeUndefined();
    }
    expect(fileToolOutput('openclaw', [...input.slice(0, 4), input[3]])).toBeUndefined();
    expect(fileToolOutput('hermes', input)).toBeUndefined();
    expect(fileToolOutput('other', input)).toBeUndefined();
  });
});
