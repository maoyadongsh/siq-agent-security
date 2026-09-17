import { describe, expect, it } from 'vitest';
import type { Confirmation } from './types';
import {
  classifyTaskRead,
  isTaskExecutionView,
  taskExecutionCandidate,
  taskExecutionIntentLines,
  taskExecutionIsTerminal,
  taskExecutionLinkage,
  taskExecutionReadRequest,
  taskExecutionRedactionNote,
  taskExecutionStateLabel,
  taskExecutionStopBoundary,
  taskExecutionUnresolvedGuidance,
  type TaskExecutionView,
} from './taskExecutions';

function confirmation(overrides: Partial<Confirmation> = {}): Confirmation {
  return {
    action_id: 'act_1',
    decision_receipt_id: 'rcp-dec-1',
    decision_hash: 'a'.repeat(64),
    reservation_receipt_id: 'rcp-dec-1-exec',
    reservation_hash: 'b'.repeat(64),
    params_digest: 'c'.repeat(64),
    platform: 'openclaw',
    agent_id: 'inst_1',
    session_id: 'ses_1',
    task_id: 'task_1',
    tool: 'exec',
    tool_call_id: 'tc_1',
    operation: 'exec',
    effects: ['filesystem_write'],
    resource_refs: [{ domain: 'filesystem', digest: 'd'.repeat(64) }],
    approval_scope: 'once',
    resume_mode: 'retry_required',
    grant_id: 'grant_1',
    issued_at: '2026-09-17T00:00:00Z',
    expires_at: '2026-09-17T00:10:00Z',
    status: 'reserved',
    params_excerpt: null,
    ...overrides,
  };
}

function view(overrides: Partial<TaskExecutionView> = {}): TaskExecutionView {
  return {
    schema_version: 'openshell-task-execution-status/v1',
    task_execution_kind: 'real_sandbox_command',
    state: 'reserved',
    reason_code: 'openshell_task_reserved',
    execution_id: 'rcp-dec-1-exec',
    action_id: 'act_1',
    decision_receipt_id: 'rcp-dec-1',
    reservation_receipt_id: 'rcp-dec-1-exec',
    platform: 'openclaw',
    session_id: 'ses_1',
    agent_id: 'inst_1',
    tool: 'exec',
    target: 'inst_1',
    policy_revision: '3',
    policy_digest: 'e'.repeat(64),
    argv_digest: 'f'.repeat(64),
    ...overrides,
  };
}

const succeeded = view({
  state: 'succeeded',
  reason_code: 'openshell_task_succeeded',
  remote_exit_code: 0,
  output: { digest: '1'.repeat(64), bytes: 12, truncated: false, raw_stored: false, raw_opt_in: false },
});

describe('task execution response validation', () => {
  it('accepts a well-formed projection', () => {
    expect(isTaskExecutionView(view())).toBe(true);
    expect(isTaskExecutionView(succeeded)).toBe(true);
  });

  it('refuses a document that carries a task_executed flag', () => {
    // `/v1/openshell/session-executions` is policy_apply and reports
    // task_executed=false. Reading it as a task state would report a policy
    // application as a task execution, so it is refused outright.
    expect(isTaskExecutionView({ ...view(), task_executed: false })).toBe(false);
    expect(isTaskExecutionView({ ...view(), task_executed: true })).toBe(false);
  });

  it('refuses a success that is not backed by an exit code and an output record', () => {
    const { output: _output, ...noOutput } = succeeded;
    expect(isTaskExecutionView(noOutput)).toBe(false);
    expect(isTaskExecutionView({ ...succeeded, remote_exit_code: 1 })).toBe(false);
  });

  it('refuses unredacted output that is not also an explicit opt-in', () => {
    const base = succeeded.output!;
    expect(isTaskExecutionView({ ...succeeded, output: { ...base, raw_stored: true } })).toBe(false);
    expect(isTaskExecutionView({ ...succeeded, output: { ...base, raw_stored: true, raw_opt_in: true } })).toBe(true);
  });

  it('refuses a stop record that claims a remote stop', () => {
    const stop = {
      requested_at: '2026-09-17T00:01:00Z',
      local_cli_termination: 'terminated',
      remote_stop: 'supported',
      remote_stop_confirmed: true,
    };
    expect(isTaskExecutionView({ ...view({ state: 'stop_requested' }), stop })).toBe(false);
    expect(
      isTaskExecutionView({
        ...view({ state: 'stop_requested' }),
        stop: { ...stop, remote_stop: 'unsupported', remote_stop_confirmed: false },
      }),
    ).toBe(true);
  });

  it('refuses an unknown state or a foreign contract version', () => {
    expect(isTaskExecutionView({ ...view(), state: 'probably_fine' })).toBe(false);
    expect(isTaskExecutionView({ ...view(), schema_version: 'openshell-task-execution-status/v2' })).toBe(false);
    expect(isTaskExecutionView({ ...view(), task_execution_kind: 'policy_apply' })).toBe(false);
  });
});

describe('task read classification', () => {
  it('only reports a view for a valid document', () => {
    expect(classifyTaskRead(200, view())).toEqual({ kind: 'view', view: view() });
    expect(classifyTaskRead(200, { ...view(), task_executed: false })).toEqual({ kind: 'invalid_response' });
  });

  it('turns a non-disclosing 404 into "not a task execution" rather than a state', () => {
    for (const error of ['openshell_task_reservation_unknown', 'openshell_task_reservation_mismatch']) {
      expect(classifyTaskRead(404, { error })).toEqual({ kind: 'not_a_task_execution' });
    }
    expect(classifyTaskRead(404, { error: 'something_else' })).toEqual({ kind: 'error', status: 404 });
  });

  it('separates session loss from permission loss', () => {
    expect(classifyTaskRead(401, { error: 'unauthorized' })).toEqual({ kind: 'unauthenticated' });
    expect(classifyTaskRead(403, { error: 'decision credential cannot call admin endpoints' })).toEqual({
      kind: 'not_administrator',
    });
    expect(classifyTaskRead(503, { error: 'task_plan_missing' })).toEqual({ kind: 'error', status: 503 });
  });
});

describe('candidate selection and request shape', () => {
  it('requires both the exec tool and a reservation', () => {
    expect(taskExecutionCandidate(confirmation())).toBe(true);
    expect(taskExecutionCandidate(confirmation({ reservation_receipt_id: '' }))).toBe(false);
    expect(taskExecutionCandidate(confirmation({ tool: 'message.send' }))).toBe(false);
  });

  it('sends binding fields only, never the approved parameters', () => {
    const body = taskExecutionReadRequest(confirmation());
    expect(body).toEqual({
      schema_version: 'openshell-task-execution-status-request/v1',
      platform: 'openclaw',
      session_id: 'ses_1',
      agent_id: 'inst_1',
      tool: 'exec',
      action_id: 'act_1',
      decision_receipt_id: 'rcp-dec-1',
      reservation_receipt_id: 'rcp-dec-1-exec',
    });
    const encoded = JSON.stringify(body);
    expect(encoded).not.toContain('params_digest');
    expect(encoded).not.toContain('args');
    expect(encoded).not.toContain('argv');
  });
});

describe('state wording', () => {
  it('reserves the word success for the recorded exit code 0 and nothing else', () => {
    expect(taskExecutionStateLabel(succeeded)).toContain('退出码 0');
    expect(taskExecutionStateLabel(view({ state: 'failed', reason_code: 'openshell_task_failed', remote_exit_code: 3 }))).toContain('非零');
    expect(taskExecutionStateLabel(view({ state: 'uncertain', reason_code: 'openshell_task_result_uncertain' }))).toContain('不确定');
    // Reconciliation closes a reservation; it is not a success.
    expect(taskExecutionStateLabel(view({ state: 'reconciled_occurred', reason_code: 'openshell_task_confirmed_occurred' }))).not.toContain('成功');
    expect(taskExecutionStateLabel(view({ state: 'reconciled_not_occurred', reason_code: 'openshell_task_confirmed_not_occurred' }))).not.toContain('成功');
  });

  it('keeps a policy-side refusal from reading as a task result', () => {
    const unverified = view({ state: 'policy_unverified', reason_code: 'openshell_task_policy_not_loaded' });
    expect(taskExecutionStateLabel(unverified)).toContain('未发起任务');
  });

  it('treats reserved, running and uncertain as unresolved', () => {
    expect(taskExecutionIsTerminal(view())).toBe(false);
    expect(taskExecutionIsTerminal(view({ state: 'running', reason_code: 'openshell_task_running' }))).toBe(false);
    expect(taskExecutionIsTerminal(view({ state: 'uncertain', reason_code: 'openshell_task_result_uncertain' }))).toBe(false);
    for (const state of ['failed', 'output_limited', 'timed_out', 'stop_requested'] as const) {
      expect(taskExecutionIsTerminal(view({ state }))).toBe(false);
      expect(taskExecutionUnresolvedGuidance(view({ state }))).toContain('对账');
    }
    expect(taskExecutionIsTerminal(succeeded)).toBe(true);
  });

  it('guides unresolved reservations toward reconciliation, never toward replay', () => {
    const guidance = taskExecutionUnresolvedGuidance(view({ state: 'uncertain', reason_code: 'openshell_task_result_uncertain' }));
    expect(guidance).toContain('对账');
    expect(guidance).toContain('不会重新执行');
    expect(guidance).toContain('不要重复提交');
    expect(taskExecutionUnresolvedGuidance(succeeded)).toBeNull();
  });

  it('never offers a stop this console cannot perform, and never claims a remote stop', () => {
    const running = taskExecutionStopBoundary(view({ state: 'running', reason_code: 'openshell_task_running', started_at: '2026-09-17T00:00:30Z' }));
    expect(running).toContain('无法发起停止');
    expect(running).toContain('当前未确认远端停止');
    expect(running).toContain('不等于远端任务已停止');
    const stopped = taskExecutionStopBoundary(
      view({
        state: 'stop_requested',
        reason_code: 'openshell_task_stop_requested_local_only',
        stop: {
          requested_at: '2026-09-17T00:02:00Z',
          local_cli_termination: 'terminated',
          remote_stop: 'unsupported',
          remote_stop_confirmed: false,
        },
      }),
    );
    expect(stopped).toContain('terminated');
    expect(stopped).not.toContain('已停止。');
  });
});

describe('operator-facing summaries', () => {
  it('describes the approved intent before execution without inventing permissions', () => {
    const lines = taskExecutionIntentLines(confirmation());
    const byLabel = Object.fromEntries(lines.map((line) => [line.label, line.value]));
    expect(byLabel['是否新增权限']).toContain('仅批准本次一次执行');
    expect(byLabel['目标']).toBe('inst_1');
    expect(byLabel['参数摘要']).toBe('c'.repeat(64));
    expect(byLabel['预期副作用']).toBe('filesystem_write');
  });

  it('flags a scope that is not one-shot instead of calling it a one-time approval', () => {
    const lines = taskExecutionIntentLines(confirmation({ approval_scope: 'session' as Confirmation['approval_scope'] }));
    expect(lines.find((line) => line.label === '是否新增权限')?.value).toContain('长期权限');
  });

  it('links approval, reservation, task and receipts using only identifiers that exist', () => {
    const labels = taskExecutionLinkage(succeeded).map((row) => row.label);
    expect(labels).toEqual(['执行标识', '动作', '批准回执', '预留回执']);
    const full = taskExecutionLinkage(
      view({
        task_id: 'task_1',
        runtime_task_id: 'rt_1',
        result_receipt_id: 'rcp-res-1',
        reconciliation_receipt_id: 'rcp-rec-1',
      }),
    ).map((row) => row.label);
    expect(full).toContain('结果回执');
    expect(full).toContain('对账回执');
    expect(full).toContain('运行任务');
    expect(full).toContain('任务');
  });

  it('states the default redaction and reports an opt-in only when the backend recorded one', () => {
    expect(taskExecutionRedactionNote(null)).toContain('原文未保存');
    expect(taskExecutionRedactionNote(view())).toContain('原文未保存');
    const optedIn = view({ output: { digest: '2'.repeat(64), bytes: 1, truncated: false, raw_stored: true, raw_opt_in: true } });
    expect(taskExecutionRedactionNote(optedIn)).toContain('另行授权');
  });
});
