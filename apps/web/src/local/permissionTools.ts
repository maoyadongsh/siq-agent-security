// Presentation of the explicit names handled by runtimeaction.normalizeEffects.
// Names are never expanded into toolsets, rewritten for submission or auto-granted.
const labels: Record<string, string> = {
  read_file: '读取文件', read: '读取文件', cat: '读取文件', search_files: '搜索文件',
  write_file: '写入文件', write: '写入文件', edit: '编辑文件', patch: '修改文件',
  delete_file: '删除文件', remove: '删除文件',
  web_fetch: '读取网页', web_extract: '提取网页', web_search: '搜索网页',
  fetch: '请求网络服务', http: '请求网络服务', http_request: '请求网络服务',
  webfetch: '读取网页', websearch: '搜索网页', browser: '使用浏览器', browser_navigate: '浏览网页',
  terminal: '执行命令', exec: '执行命令', bash: '执行命令', shell: '执行命令', process: '运行进程',
  sh: '执行命令', python: '运行 Python', python3: '运行 Python', node: '运行 JavaScript',
  powershell: '执行 PowerShell', pwsh: '执行 PowerShell',
  send_message: '发送消息', message: '发送消息',
};
export function permissionToolLabel(name: string): string {
  return `${labels[name.toLowerCase()] ?? '自定义工具或工具组'}（${name}）`;
}
export function permissionToolNames(text: string): string[] {
  return text.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
}
export function readOnlyTools(names: string[]): string[] {
  return names.filter((name) => ['read_file', 'read', 'cat', 'search_files'].includes(name.toLowerCase()));
}
export interface PermissionDraft {
  tools: string; readOnly: string; readWrite: string; networkAllow: string; networkDeny: string; models: string;
}
export function readOnlyDraft(draft: PermissionDraft, paths: (text: string) => string[]): PermissionDraft {
  return { ...draft, tools: readOnlyTools(permissionToolNames(draft.tools)).join('\n'),
    readOnly: Array.from(new Set([...paths(draft.readOnly), ...paths(draft.readWrite)])).join('\n'),
    readWrite: '', networkAllow: '', models: '' };
}
