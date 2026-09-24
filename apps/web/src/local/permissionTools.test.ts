import { describe, expect, it } from 'vitest';
import { permissionToolLabel, permissionToolNames, readOnlyDraft, readOnlyTools } from './permissionTools';
import { windowsPathLines } from './filesystemProfile';

describe('read-only permission proposal', () => {
  it('keeps a subset of explicitly selected tools, including original spelling', () => {
    const original = ['read_file', 'Read', 'search_files', 'terminal', 'file', 'mcp_read_admin', 'write_file', 'web_fetch', '*'];
    const kept = readOnlyTools(original);
    expect(kept).toEqual(['read_file', 'Read', 'search_files']);
    expect(kept.every((name) => original.includes(name))).toBe(true);
    expect(readOnlyTools([])).toEqual([]);
    expect(readOnlyTools(['file', 'read_file;exec', 'unknown_reader'])).toEqual([]);
  });
  it('reduces editable permissions while preserving exact deny and path values', () => {
    const draft = { tools: 'read_file\nwrite_file\nterminal', readOnly: '/reports with spaces,commas',
      readWrite: '/output\n/reports with spaces,commas', networkAllow: 'public.example:443',
      networkDeny: 'private.example:443', models: 'declared-model' };
    const result = readOnlyDraft(draft, permissionToolNames);
    expect(result).toEqual({ tools: 'read_file', readOnly: '/reports with spaces,commas\n/output',
      readWrite: '', networkAllow: '', networkDeny: 'private.example:443', models: '' });
    expect(draft.readWrite).toBe('/output\n/reports with spaces,commas');
  });
  it('preserves Windows raw path whitespace so invalid input is rejected by the server', () => {
    const result = readOnlyDraft({ tools: 'read', readOnly: ' C:\\reports ', readWrite: 'C:\\output',
      networkAllow: '', networkDeny: '', models: '' }, windowsPathLines);
    expect(result.readOnly).toBe(' C:\\reports \nC:\\output');
  });
  it('does not describe unknown tools as safe or available', () => {
    expect(permissionToolLabel('file')).toBe('自定义工具或工具组（file）');
    expect(permissionToolLabel('mcp_read_admin')).toBe('自定义工具或工具组（mcp_read_admin）');
    expect(permissionToolLabel('terminal')).toBe('执行命令（terminal）');
  });
});
