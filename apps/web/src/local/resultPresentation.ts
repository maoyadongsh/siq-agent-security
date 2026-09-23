import type { CompletionStatus } from './taskCompletion';

export function resultPresentation(status: CompletionStatus, reason: string): { label: string; explanation: string; next: string } {
  if (status === 'verified') return { label: '结果核验通过', explanation: '已按任务要求核对独立观测证据。', next: '可逐项查看证据；核验范围以本页要求为准。' };
  if (status === 'conflicting') return { label: '结果需要核查', explanation: reason === 'task_security_incident' ? '发现与本任务相关的安全事件。' : '结果证据之间存在冲突。', next: '先查看相关证据并核查实际影响，避免直接重复执行。' };
  if (status === 'incomplete' && reason === 'effect_failed') return { label: '观测到执行失败', explanation: '至少一项要求有失败观测，尚未通过结果核验。', next: '查看该项证据，确认失败原因与实际影响后再决定如何处理。' };
  if (status === 'incomplete') return { label: '结果待核验', explanation: '尚未收到满足全部要求的结果证据。', next: '若执行端仍在工作，可稍后刷新详情；缺少证据不表示任务仍在运行或已经失败。' };
  if (reason === 'not_required') return { label: '未设置结果核验', explanation: '此任务未定义可核验的结果要求。', next: '请到发起任务的业务系统查看实际输出；当前调用记录不能证明任务完成。' };
  if (reason === 'intent_missing') return { label: '结果无法确认', explanation: '未找到对应签名意图，无法核验实际效果。', next: '请确认任务的授权记录仍可读取，再刷新详情。' };
  if (reason === 'attribution_unknown') return { label: '结果无法确认', explanation: '缺少可信任务归属，无法核验实际效果。', next: '请从已接入实例发起任务并确认其运行记录，不能按时间或名称猜测归属。' };
  return { label: '结果无法确认', explanation: '现有证据不足以确认结果，可能缺少独立观测或足够的覆盖范围。', next: '查看证据来源和覆盖范围；执行方自报完成不能替代独立核验。' };
}

export const effectTypeLabel = (value: string): string => ({
  'file.write': '文件写入', 'file.read': '文件读取', 'network.request': '网络请求',
  'message.send': '消息发送', 'database.write': '数据库写入',
} as Record<string, string>)[value] ?? '其他效果类型';
