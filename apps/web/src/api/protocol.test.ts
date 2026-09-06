import { describe, expect, it } from 'vitest';
import {
  classifyContentType,
  looksLikeHtml,
  protocolErrorMessage,
} from './protocol';

describe('DEV13-A protocol guards', () => {
  it('accepts application/json', () => {
    expect(classifyContentType('application/json; charset=utf-8')).toBeNull();
  });

  it('rejects html and missing content-type', () => {
    expect(classifyContentType('text/html')).toBe('non_json_content_type');
    expect(classifyContentType(null)).toBe('missing_content_type');
    expect(classifyContentType('text/plain')).toBe('non_json_content_type');
  });

  it('detects html bodies', () => {
    expect(looksLikeHtml('<!DOCTYPE html><html>')).toBe(true);
    expect(looksLikeHtml('{"ok":true}')).toBe(false);
  });

  it('messages state protocol failure clearly', () => {
    expect(protocolErrorMessage('html_body', 200)).toMatch(/协议错误/);
    expect(protocolErrorMessage('non_array_list', 200)).toMatch(/不得回退示例数据/);
  });
});
