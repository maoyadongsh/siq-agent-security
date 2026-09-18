/**
 * 真实任务执行（`/v1/openshell/task-executions/*`）的前端纯逻辑层。
 *
 * 这一层只做两件事：把一个确认项翻译成一次**只读**查询，以及把后端返回的
 * 投影翻译成诚实的措辞。它不做任何权限判断、不缓存终态、不推断成功——后端才是
 * 状态来源。所有分支都能被单元测试覆盖，因为这里的每一个措辞都是一条对外承诺。
 *
 * 刻意与本文件同级存在的 `openshellDiagnosis.ts` 一样，本模块不 import React，
 * 也不 import api.ts：UI 之外的调用方（测试、其他页面）可以直接用它做分类。
 */
import type { Confirmation } from './types';

/** 与 `packages/contracts/openshell-task-execution-status.v1.schema.json` 对齐。 */
export const TASK_EXECUTION_STATUS_SCHEMA = 'openshell-task-execution-status/v1';
export const TASK_EXECUTION_STATUS_REQUEST_SCHEMA = 'openshell-task-execution-status-request/v1';
/**
 * 只有真实沙箱命令执行才带这个 kind。旧的 `/v1/openshell/session-executions`
 * 是 `policy_apply`（`task_executed=false`），按名字容易被误当成执行；
 * 这里用常量把两者在类型层面分开，任何不是该常量的响应都当作无法识别的响应拒绝，
 * 而不是把它渲染成任务状态。
 */
export const TASK_EXECUTION_KIND = 'real_sandbox_command';

export type TaskExecutionState =
  | 'denied'
  | 'reserved'
  | 'policy_unverified'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'output_limited'
  | 'timed_out'
  | 'stop_requested'
  | 'uncertain'
  | 'reconciled_occurred'
  | 'reconciled_not_occurred';

const TASK_EXECUTION_STATES: readonly TaskExecutionState[] = [
  'denied',
  'reserved',
  'policy_unverified',
  'running',
  'succeeded',
  'failed',
  'output_limited',
  'timed_out',
  'stop_requested',
  'uncertain',
  'reconciled_occurred',
  'reconciled_not_occurred',
];

export interface TaskExecutionOutput {
  digest: string;
  stderr_digest?: string;
  bytes: number;
  truncated: boolean;
  raw_stored: boolean;
  raw_opt_in: boolean;
}

export interface TaskExecutionStop {
  requested_at: string;
  local_cli_termination: 'not_running' | 'requested' | 'terminated' | 'refused';
  remote_stop: 'unsupported';
  remote_stop_confirmed: false;
  actor_id?: string;
  note?: string;
}

export interface TaskExecutionView {
  schema_version: typeof TASK_EXECUTION_STATUS_SCHEMA;
  task_execution_kind: typeof TASK_EXECUTION_KIND;
  state: TaskExecutionState;
  reason_code: string;
  execution_id: string;
  action_id: string;
  decision_receipt_id: string;
  reservation_receipt_id?: string;
  result_receipt_id?: string;
  reconciliation_receipt_id?: string;
  platform: string;
  session_id: string;
  agent_id: string;
  task_id?: string;
  runtime_task_id?: string;
  tool: 'exec';
  target: string;
  policy_revision: string;
  policy_digest: string;
  argv_digest: string;
  argv_preview?: string[];
  started_at?: string;
  finished_at?: string;
  remote_exit_code?: number;
  timeout_seconds?: number;
  timeout_bound_that_fired?: 'remote' | 'local' | 'none';
  output?: TaskExecutionOutput;
  stop?: TaskExecutionStop;
  note?: string;
}

/** 一次查询的结果分类。`view` 之外的每一种都不是状态，UI 不得据此宣布任何结论。 */
export type TaskReadOutcome =
  | { kind: 'view'; view: TaskExecutionView }
  /** 该预留不是 OpenShell 任务执行（未知或身份不匹配）。没有可展示的状态。 */
  | { kind: 'not_a_task_execution' }
  /** 响应不是本契约的文档（含携带 `task_executed` 的其他接口）。 */
  | { kind: 'invalid_response' }
  /** 管理会话失效，需要重新配对。 */
  | { kind: 'unauthenticated' }
  /** 当前凭据不是管理会话（控制台持管理会话，出现即说明调用路径错误）。 */
  | { kind: 'not_administrator' }
  | { kind: 'error'; status: number };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isOptionalText(value: unknown): boolean {
  return value === undefined || typeof value === 'string';
}

function isHex64(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
}

function isTaskExecutionOutput(value: unknown): value is TaskExecutionOutput {
  if (!isRecord(value)) return false;
  if (!isHex64(value.digest)) return false;
  if (value.stderr_digest !== undefined && !isHex64(value.stderr_digest)) return false;
  if (typeof value.bytes !== 'number' || !Number.isInteger(value.bytes) || value.bytes < 0) return false;
  if (typeof value.truncated !== 'boolean') return false;
  if (typeof value.raw_stored !== 'boolean') return false;
  if (typeof value.raw_opt_in !== 'boolean') return false;
  // 契约的 allOf：存了原文就必然是一次显式选择。违反它的响应宁可整份拒绝，
  // 也不能渲染成"可选地看到了原文"。
  if (value.raw_stored && !value.raw_opt_in) return false;
  return true;
}

function isTaskExecutionStop(value: unknown): value is TaskExecutionStop {
  if (!isRecord(value)) return false;
  if (!isText(value.requested_at)) return false;
  if (!['not_running', 'requested', 'terminated', 'refused'].includes(value.local_cli_termination as string)) return false;
  // 远端停止是未证能力，契约把它钉死。任何声称远端已停的响应都必须被拒绝。
  if (value.remote_stop !== 'unsupported') return false;
  if (value.remote_stop_confirmed !== false) return false;
  if (!isOptionalText(value.actor_id)) return false;
  if (!isOptionalText(value.note)) return false;
  return true;
}

/**
 * 严格的响应校验。这里宁可多拒也不肯少拒：凡是无法从契约推出的事实，
 * 一律不进入 UI。特别地，`task_executed` 顶层字段被明确拒绝——本契约没有它，
 * 出现它就说明对面是另一个接口（例如 policy_apply 家族的 `task_executed=false`），
 * 把它当任务状态读会把"策略已应用"误报成"任务已执行"。
 */
export function isTaskExecutionView(data: unknown): data is TaskExecutionView {
  if (!isRecord(data)) return false;
  if ('task_executed' in data) return false;
  if (data.schema_version !== TASK_EXECUTION_STATUS_SCHEMA) return false;
  if (data.task_execution_kind !== TASK_EXECUTION_KIND) return false;
  if (data.tool !== 'exec') return false;
  if (!TASK_EXECUTION_STATES.includes(data.state as TaskExecutionState)) return false;
  if (!isText(data.reason_code)) return false;
  for (const key of [
    'execution_id',
    'action_id',
    'decision_receipt_id',
    'platform',
    'session_id',
    'agent_id',
    'target',
  ] as const) {
    if (!isText(data[key])) return false;
  }
  for (const key of [
    'reservation_receipt_id',
    'result_receipt_id',
    'reconciliation_receipt_id',
    'task_id',
    'runtime_task_id',
    'started_at',
    'finished_at',
    'note',
  ] as const) {
    if (!isOptionalText(data[key])) return false;
  }
  if (!isHex64(data.policy_digest)) return false;
  if (!isHex64(data.argv_digest)) return false;
  if (typeof data.policy_revision !== 'string' || !/^[1-9][0-9]{0,18}$/.test(data.policy_revision)) return false;
  if (data.output !== undefined && !isTaskExecutionOutput(data.output)) return false;
  if (data.stop !== undefined && !isTaskExecutionStop(data.stop)) return false;
  if (data.remote_exit_code !== undefined) {
    const code = data.remote_exit_code;
    if (typeof code !== 'number' || !Number.isInteger(code) || code < -1 || code > 255) return false;
  }
  if (data.state === 'succeeded' && data.remote_exit_code !== 0) return false;
  if (data.state === 'succeeded' && data.output === undefined) return false;
  if (data.state === 'failed' && data.output === undefined) return false;
  if (data.argv_preview !== undefined) {
    if (!Array.isArray(data.argv_preview)) return false;
    if (data.argv_preview.length > 256) return false;
    if (!data.argv_preview.every((arg) => typeof arg === 'string')) return false;
  }
  return true;
}

/**
 * 该确认项是不是一次 OpenShell 任务执行的候选。
 *
 * 后端的 status 请求形状校验要求 `tool === "exec"`，所以这是发起查询的必要条件；
 * 但它不是充分条件（其他平台的 hold 也可能用 `exec`）。真正的判定在服务端：
 * 不匹配的预留会返回 404，那时唯一诚实的说法是"这不是任务执行"，
 * 而不是"状态未知"——后者会凭空造出一个待观察的任务。
 *
 * 预留号非空同样是必要条件：没有 `-exec` 预留就没有可查询的执行。
 */
export function taskExecutionCandidate(item: Confirmation): boolean {
  return item.tool === 'exec' && typeof item.reservation_receipt_id === 'string' && item.reservation_receipt_id.length > 0;
}

/** 组装 `/v1/openshell/task-executions/read` 的请求体（仅绑定字段，无原始参数）。 */
export function taskExecutionReadRequest(item: Confirmation): Record<string, string> {
  return {
    schema_version: TASK_EXECUTION_STATUS_REQUEST_SCHEMA,
    platform: item.platform,
    session_id: item.session_id,
    agent_id: item.agent_id,
    tool: item.tool,
    action_id: item.action_id,
    decision_receipt_id: item.decision_receipt_id,
    reservation_receipt_id: item.reservation_receipt_id,
  };
}

/** 把一次 HTTP 结果归类。状态码与错误码的映射保持与后端一致。 */
export function classifyTaskRead(status: number, body: unknown): TaskReadOutcome {
  if (status === 200) {
    return isTaskExecutionView(body) ? { kind: 'view', view: body } : { kind: 'invalid_response' };
  }
  if (status === 401) return { kind: 'unauthenticated' };
  if (status === 403) return { kind: 'not_administrator' };
  if (status === 404) {
    const error = isRecord(body) && typeof body.error === 'string' ? body.error : '';
    // 预留不存在，或存在但不属于这个绑定。两者都是同一个不披露的答案：
    // 这不是本控制台能看到的任务执行。
    if (error === 'openshell_task_reservation_unknown' || error === 'openshell_task_reservation_mismatch') {
      return { kind: 'not_a_task_execution' };
    }
    return { kind: 'error', status };
  }
  return { kind: 'error', status };
}

/**
 * 状态标签。措辞规则：只有后端记录的 `succeeded` 才能出现"返回 0"，
 * 其余一律描述"已记录的事实"，不描述"结果好坏"。
 */
export function taskExecutionStateLabel(view: TaskExecutionView): string {
  switch (view.state) {
    case 'reserved':
      return '已预留一次执行，尚未启动';
    case 'policy_unverified':
      return '策略未确认：未发起任务（策略侧事实单独留账）';
    case 'denied':
      return '执行前校验未通过，未产生任务副作用';
    case 'running':
      return '已启动，结果尚未落盘';
    case 'succeeded':
      return '后端已记录执行完成，远端退出码 0';
    case 'failed':
      return `后端已记录非零退出码 ${view.remote_exit_code ?? '未知'}（与本地进程失败无法区分）`;
    case 'output_limited':
      return '输出超过上限，已截断记录';
    case 'timed_out':
      return view.timeout_bound_that_fired === 'remote' ? '远端超时' : '本地超时';
    case 'stop_requested':
      return '已请求停止：仅本地 CLI 进程，当前未确认远端停止';
    case 'uncertain':
      return '执行结果不确定，预留未决，需管理员对账';
    case 'reconciled_occurred':
      return '管理员凭外部证据结案：确认已发生（不重放）';
    case 'reconciled_not_occurred':
      return '管理员凭外部证据结案：确认未发生（不重放）';
  }
}

/** 无待对账预留的终态。失败、超时、截断和本地停止仍可由管理员对账。 */
export function taskExecutionIsTerminal(view: TaskExecutionView): boolean {
  return ['succeeded', 'denied', 'reconciled_occurred', 'reconciled_not_occurred'].includes(
    view.state,
  );
}

/**
 * 未决时的下一步说明。刻意**不**提供"重新执行"建议：预留仍在，重放会绕过
 * 唯一预留的语义。文本描述的是对账，而不是重试。
 */
export function taskExecutionUnresolvedGuidance(view: TaskExecutionView): string | null {
  if (taskExecutionIsTerminal(view)) return null;
  if (view.state === 'running') return '本进程仍在观察任务；请重新读取状态。不要重复提交同一操作。';
  if (view.state === 'reserved') return '执行已预留，尚无启动记录；请重新读取状态。不要重复提交同一操作。';
  return '预留仍处于未决状态。请在目标系统核对文件、消息或外部服务结果后交由管理员对账；对账只记录结论，不会重新执行。不要重复提交同一操作。';
}

/**
 * 停止能力的诚实描述。控制台持管理会话，而停止接口要求决策凭据，
 * 因此这里**不能**提供停止按钮；即使对决策凭据持有者，停止也只作用于本地 CLI 进程。
 */
export function taskExecutionStopBoundary(view: TaskExecutionView): string {
  const base = '本控制台持管理会话，不具备停止决策凭据，无法发起停止。';
  if (view.state === 'running') {
    return `${base}且即便由决策凭据发起，停止也只终止本地 CLI 进程（当前未确认远端停止、无远端确认）；本地进程退出不等于远端任务已停止，请以对账结论为准。`;
  }
  if (view.stop) {
    return `${base}已有停止记录：本地 CLI ${view.stop.local_cli_termination}；远端是否停止仍未确认。`;
  }
  return base;
}

/** 审批 / 预留 / 任务 / 回执的关联事实，只列真实存在的标识。 */
export function taskExecutionLinkage(view: TaskExecutionView): { label: string; value: string }[] {
  const rows: { label: string; value: string }[] = [
    { label: '执行标识', value: view.execution_id },
    { label: '动作', value: view.action_id },
    { label: '批准回执', value: view.decision_receipt_id },
  ];
  if (view.reservation_receipt_id) rows.push({ label: '预留回执', value: view.reservation_receipt_id });
  if (view.task_id) rows.push({ label: '任务', value: view.task_id });
  if (view.runtime_task_id) rows.push({ label: '运行任务', value: view.runtime_task_id });
  if (view.result_receipt_id) rows.push({ label: '结果回执', value: view.result_receipt_id });
  if (view.reconciliation_receipt_id) rows.push({ label: '对账回执', value: view.reconciliation_receipt_id });
  return rows;
}

/**
 * 执行前对用户说明的四件事：目标、具体动作、资源权限、是否新增长期权限、
 * 预期副作用。这些全部来自已批准的确认项本身，不来自模型输出。
 */
export function taskExecutionIntentLines(item: Confirmation): { label: string; value: string }[] {
  const lines: { label: string; value: string }[] = [
    { label: '目标', value: item.agent_id },
    { label: '具体动作', value: item.tool === 'exec' ? '在目标沙箱内执行一次已批准的命令' : item.tool },
    { label: '运行任务', value: item.task_id || item.runtime_task_id || '—' },
    { label: '资源指纹', value: item.resource_refs.length ? item.resource_refs.map((ref) => `${ref.domain}:${ref.digest.slice(0, 12)}…`).join('，') : '无外部资源' },
    {
      label: '是否新增权限',
      value:
        item.approval_scope === 'once'
          ? '否，仅批准本次一次执行'
          : `批准范围 ${item.approval_scope}，请在长期权限中核对`,
    },
    { label: '预期副作用', value: item.effects.length ? item.effects.join('，') : '未声明额外副作用' },
    { label: '参数摘要', value: item.params_digest },
  ];
  return lines;
}

/** 参数摘要来自确认项；原始参数与原始输出都不在本模块出现。 */
export function taskExecutionRedactionNote(view: TaskExecutionView | null): string {
  if (view?.output?.raw_stored) {
    return '本次执行按任务级显式选择保存了原始输出；查看原文需另行授权。';
  }
  return '默认只保留脱敏摘要：命令以 argv 摘要表示，输出以摘要和字节数表示，原文未保存。';
}
