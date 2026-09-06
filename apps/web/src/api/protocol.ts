/** API 协议校验（DEV13-A / R11）：200 HTML / 非 JSON / 空壳不得当成功。 */

export type ProtocolIssue =
  | 'missing_content_type'
  | 'non_json_content_type'
  | 'html_body'
  | 'null_body'
  | 'non_array_list';

export function classifyContentType(contentType: string | null): ProtocolIssue | null {
  if (!contentType || !contentType.trim()) return 'missing_content_type';
  const lower = contentType.toLowerCase();
  if (lower.includes('text/html')) return 'non_json_content_type';
  if (!lower.includes('json') && !lower.includes('application/problem')) {
    return 'non_json_content_type';
  }
  return null;
}

export function protocolErrorMessage(issue: ProtocolIssue, status: number): string {
  switch (issue) {
    case 'missing_content_type':
      return `协议错误：HTTP ${status} 缺少 Content-Type（期望 application/json）`;
    case 'non_json_content_type':
      return `协议错误：HTTP ${status} 返回非 JSON（疑似 HTML/网关页），不得当作业务成功`;
    case 'html_body':
      return `协议错误：HTTP ${status} 正文为 HTML，不得当作业务成功`;
    case 'null_body':
      return `协议错误：HTTP ${status} 正文无法解析为 JSON`;
    case 'non_array_list':
      return `协议错误：列表接口返回非数组，不得回退示例数据并显示已连接`;
    default:
      return `协议错误：HTTP ${status}`;
  }
}

/** 粗检正文是否像 HTML（在 Content-Type 漏标时兜底）。 */
export function looksLikeHtml(text: string): boolean {
  const head = text.trimStart().slice(0, 64).toLowerCase();
  return head.startsWith('<!doctype html') || head.startsWith('<html');
}
