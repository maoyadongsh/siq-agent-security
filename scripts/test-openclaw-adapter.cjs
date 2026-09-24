// Isolated hook contract tests; never read the developer's platform config/token.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../apps/web/node_modules/typescript');
const sourcePath = path.join(__dirname, '../adapters/runtime/openclaw-agentshield/index.ts');
const source = fs.readFileSync(sourcePath, 'utf8').replace(
  'import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";',
  'const definePluginEntry = (value: any) => value;',
);
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true });
assert.equal(output.diagnostics.length, 0);
const hooks = {};
const seen = [];
const configReads = [];
let decision = { action: 'allow', action_id: 'act-1', receipt_id: 'rcp-1', reason: 'approved' };
let unavailable = false;
let approvalMode = 'approved';
let statusQueries = 0;
let reserveAccepts = () => true;
const exportsObject = {};
const sandbox = {
  exports: exportsObject,
  process: { env: { OPENCLAW_STATE_DIR: '/isolated-profile' }, platform: 'linux' },
  console: { warn() {} },
  setTimeout, clearTimeout, AbortController, URL, Buffer,
  require(name) {
    if (name === 'node:fs') return {
      constants: { O_RDONLY: 0, O_NOFOLLOW: 0 },
      lstatSync() { return { isFile: () => true, size: 64, ino: 1, dev: 1 }; },
      fstatSync() { return { isFile: () => true, size: 64, ino: 1, dev: 1 }; },
      openSync() { return 1; }, closeSync() {},
      readSync(fd, buffer) { buffer.write('t'.repeat(64)); return 64; },
      readFileSync(p) {
        if (p.endsWith('/token')) return 't'.repeat(64);
        configReads.push(p);
        if (p === '/isolated-profile/siq-agent-security.json') return JSON.stringify({ tokenPath: '/isolated-profile/decision/token', holdWaitMs: 500 });
        throw Error('unexpected config location');
      },
      mkdirSync() {}, appendFileSync() {},
    };
    if (name === 'node:os') return { homedir: () => '/isolated-test' };
    // The VM deliberately models Linux. Keep its path implementation aligned
    // even when the contract harness itself runs on Windows.
    if (name === 'node:path') return path.posix;
    if (name === 'node:crypto') return crypto;
    throw Error('unexpected import: ' + name);
  },
  fetch: async (url, options) => {
    if (unavailable) throw Error('offline');
    seen.push({ url, body: JSON.parse(options.body) });
    if (url.endsWith('/v1/hold-status')) {
      statusQueries++;
      if (approvalMode === 'offline') throw Error('offline');
      const state = approvalMode === 'pending-then-approved' ? (statusQueries === 1 ? 'pending' : 'approved') : approvalMode;
      const status = {
        schema_version: 'hold-status/v1', action_id: decision.action_id, decision_receipt_id: decision.receipt_id,
        status: state, reason_code: 'hold_' + state, expires_at: new Date(Date.now() + 60000).toISOString(),
      };
      if (approvalMode === 'wrong-action') Object.assign(status, { status: 'approved', reason_code: 'hold_approved', action_id: 'forged' });
      if (approvalMode === 'stale') Object.assign(status, { status: 'approved', reason_code: 'hold_approved', expires_at: new Date(0).toISOString() });
      if (approvalMode === 'invalid-time') Object.assign(status, { status: 'approved', reason_code: 'hold_approved', expires_at: '2099' });
      return { status: 200, json: async () => status };
    }
    if (url.endsWith('/v1/hold-executions/reserve')) {
      const request = JSON.parse(options.body);
      if (!reserveAccepts(request)) return { status: 409, json: async () => ({}) };
      return {
        status: 201,
        json: async () => ({
          schema_version: 'hold-execution-status/v1',
          status: 'reserved',
          action_id: request.action_id,
          decision_receipt_id: request.decision_receipt_id,
          reservation_receipt_id: `${request.decision_receipt_id}-exec`,
          expires_at: new Date(Date.now() + 60000).toISOString(),
          reason_code: 'hold_execution_reserved',
        }),
      };
    }
    return { status: 200, json: async () => decision };
  },
};
vm.runInNewContext(output.outputText, sandbox, { filename: sourcePath });
assert.deepEqual(configReads, ['/isolated-profile/siq-agent-security.json'], 'isolated platform state must not read the default user config');
exportsObject.default.register({ on(name, callback) { hooks[name] = callback; } });
(async () => {
  const event = { toolName: 'read_file', toolCallId: 'call-1', params: { path: '/approved/report' }, result: 'ok' };
  const context = { sessionKey: 'session-1', sessionId: '11111111-1111-4111-8111-111111111111', agentId: 'agent-1', approvalExecutionRecheckVersion: 1 };
  const firstIdentity = exportsObject.nativeSessionID(context);
  const vector = JSON.parse(fs.readFileSync(path.join(__dirname, '../apps/agentshield/testdata/contracts/openclaw-native-session.json'), 'utf8'));
  assert.equal(exportsObject.nativeSessionID({ ...context, sessionKey: 'agent:fixture:main' }), vector);
  const nextContext = { ...context, sessionId: '22222222-2222-4222-8222-222222222222' };
  assert.match(firstIdentity, /^openclaw-session\/v1:[0-9a-f]{64}$/);
  assert.equal(exportsObject.nativeSessionID({ ...context }), firstIdentity);
  assert.notEqual(exportsObject.nativeSessionID(nextContext), firstIdentity);
  const previousRequests = seen.length;
  assert.equal((await hooks.before_tool_call({ ...event, sessionKey: context.sessionKey, sessionId: context.sessionId,
    params: { sessionKey: context.sessionKey, sessionId: context.sessionId } }, {})).block, true);
  assert.equal(seen.length, previousRequests, 'event/model data cannot supply trusted epoch');
  assert.equal(await hooks.before_tool_call({ ...event, toolCallId: 'epoch-source', sessionId: nextContext.sessionId }, context), undefined);
  assert.equal(seen.at(-1).body.session_id, firstIdentity, 'event override ignored');
  await hooks.after_tool_call({ ...event, toolCallId: 'epoch-source' }, nextContext);
  assert.equal(seen.at(-1).body.action_id, undefined, 'new epoch cannot observe prior decision');
  assert.equal(await hooks.before_tool_call({ ...event, toolCallId: 'epoch-source' }, nextContext), undefined);
  assert.equal(seen.at(-1).body.session_id, exportsObject.nativeSessionID(nextContext));
  assert.equal(await hooks.before_tool_call(event, context), undefined);
  await hooks.after_tool_call(event, context);
  assert.equal(seen.at(-1).body.action_id, 'act-1');
  assert.equal(seen.at(-1).body.decision_receipt_id, 'rcp-1');
  assert.equal(seen.at(-1).body.tool_call_id, 'call-1');
  decision = { ...decision, action_id: 'act-2', receipt_id: 'rcp-2' };
  assert.equal((await hooks.before_tool_call(event, context)).block, true);
  await hooks.after_tool_call(event, context);
  assert.equal(seen.at(-1).body.action_id, undefined, 'conflict must not attach the earlier decision');
  decision = { action: 'deny', receipt_id: 'denied', reason: 'outside authority' };
  assert.equal((await hooks.before_tool_call({ ...event, toolCallId: 'denied' }, context)).block, true);
  unavailable = true;
  assert.equal((await hooks.before_tool_call({ ...event, toolCallId: 'offline' }, context)).block, true);
  unavailable = false;
  for (const capability of [undefined, 0, 2, '1', true]) {
    const id = 'unsupported-' + String(capability);
    decision = { action: 'hold', action_id: 'act-' + id, receipt_id: 'rcp-' + id, reason: 'approval' };
    const previousQueries = statusQueries;
    const result = await hooks.before_tool_call(
      { ...event, toolCallId: id, approvalExecutionRecheckVersion: 1,
        params: { ...event.params, approvalExecutionRecheckVersion: 1 } },
      { ...context, approvalExecutionRecheckVersion: capability },
    );
    assert.equal(result.block, true, 'unsupported host must not enter platform approval');
    assert.equal(result.requireApproval, undefined);
    assert.equal(statusQueries, previousQueries, 'untrusted event/params cannot announce host support');
  }
  for (const mode of ['approved', 'pending-then-approved', 'denied', 'expired', 'consumed', 'wrong-action', 'stale', 'invalid-time', 'pending', 'offline']) {
    approvalMode = mode;
    statusQueries = 0;
    decision = { action: 'hold', action_id: 'act-' + mode, receipt_id: 'rcp-' + mode, reason: 'requires local approval', hold: { timeout_ms: 60000 } };
    const result = await hooks.before_tool_call({ ...event, toolCallId: 'hold-' + mode }, context);
    const shouldApprove = mode === 'approved' || mode === 'pending-then-approved';
    assert.equal(!!result.requireApproval, shouldApprove, mode);
    if (shouldApprove) {
      assert.equal(result.requireApproval.timeoutBehavior, 'deny');
      assert.equal(typeof result.requireApproval.beforeExecute, 'function');
      approvalMode = 'approved';
      assert.equal(await result.requireApproval.beforeExecute(event.params), true);
      const reserve = seen.filter(item => item.url.endsWith('/v1/hold-executions/reserve')).at(-1);
      assert.equal(reserve.body.action_id, decision.action_id);
      assert.equal(reserve.body.decision_receipt_id, decision.receipt_id);
      assert.equal(reserve.body.original_tool_call_id, 'hold-' + mode);
      assert.notEqual(reserve.body.retry_tool_call_id, reserve.body.original_tool_call_id);
      assert.deepEqual(reserve.body.params, event.params);
      for (const changed of ['denied', 'expired', 'consumed', 'wrong-action', 'stale', 'offline']) {
        approvalMode = changed;
        assert.equal(await result.requireApproval.beforeExecute(event.params), false, changed);
      }
      const aborted = new AbortController();
      aborted.abort();
      approvalMode = 'approved';
      assert.equal(await result.requireApproval.beforeExecute(event.params, aborted.signal), false);

      assert.ok(result.requireApproval.timeoutMs > 0 && result.requireApproval.timeoutMs <= 60000);
    } else assert.equal(result.block, true, mode);
    const request = seen.filter(item => item.url.endsWith('/v1/hold-status')).at(-1).body;
    assert.equal(request.action_id, decision.action_id);
    assert.equal(request.decision_receipt_id, decision.receipt_id);
    assert.equal(request.context, undefined);
    assert.equal(request.approve, undefined);
    assert.equal(request.params.path, event.params.path);
  }
  approvalMode = 'pending';
  decision = { action: 'hold', action_id: 'act-cancel', receipt_id: 'rcp-cancel', reason: 'hold' };
  const abort = new AbortController();
  setTimeout(() => abort.abort(), 25);
  const cancelled = await hooks.before_tool_call({ ...event, toolCallId: 'cancel' }, { ...context, abortSignal: abort.signal });
  assert.equal(cancelled.block, true);
  decision = { action: 'hold', receipt_id: 'missing-action', reason: 'hold' };
  assert.equal((await hooks.before_tool_call({ ...event, toolCallId: 'missing-action' }, context)).block, true);

  // BU-01/OC-01 shared business action: OpenClaw carries the exact same
  // fixed semantic tuple as Hermes. The decision service binds the final
  // digests again at reservation time, after both approval layers.
  const businessTool = 'mcp__siq_business__research_publish_report';
  const businessParams = {
    task_id: 'bu01-task-001',
    request_sha256: 'a'.repeat(64),
    approval_sha256: 'b'.repeat(64),
  };
  approvalMode = 'approved';
  decision = { action: 'hold', action_id: 'act-business', receipt_id: 'rcp-business', reason: 'approved report publication' };
  reserveAccepts = request => request.tool === businessTool &&
    JSON.stringify(request.params) === JSON.stringify(businessParams);
  const businessEvent = { toolName: businessTool, toolCallId: 'business-exact', params: businessParams };
  const businessApproval = await hooks.before_tool_call(businessEvent, context);
  assert.equal(typeof businessApproval.requireApproval.beforeExecute, 'function');
  assert.equal(await businessApproval.requireApproval.beforeExecute(businessParams), true);
  const businessReserve = seen.filter(item => item.url.endsWith('/v1/hold-executions/reserve')).at(-1).body;
  assert.equal(businessReserve.tool, businessTool);
  assert.deepEqual(businessReserve.params, businessParams);
  assert.equal(businessReserve.original_tool_call_id, 'business-exact');
  assert.notEqual(businessReserve.retry_tool_call_id, businessReserve.original_tool_call_id);
  await hooks.after_tool_call({ ...businessEvent, result: { ok: true, readback_verified: true } }, context);
  const businessObservation = seen.filter(item => item.url.endsWith('/v1/observe')).at(-1).body;
  assert.equal(businessObservation.tool, businessTool);
  assert.deepEqual(businessObservation.params, businessParams);
  assert.equal(businessObservation.tool_call_id, businessReserve.retry_tool_call_id);
  assert.equal(businessObservation.decision_receipt_id, 'rcp-business-exec');

  decision = { action: 'hold', action_id: 'act-business-changed', receipt_id: 'rcp-business-changed', reason: 'approved report publication' };
  const changedEvent = { ...businessEvent, toolCallId: 'business-changed' };
  const changedApproval = await hooks.before_tool_call(changedEvent, context);
  assert.equal(await changedApproval.requireApproval.beforeExecute({ ...businessParams, request_sha256: '0'.repeat(64) }), false);
  assert.equal(seen.filter(item => item.url.endsWith('/v1/observe') && item.body.tool_call_id === 'business-changed').length, 0);
  reserveAccepts = () => true;
  for (const mode of ['warn', 'audit_only']) {
    const modeExports = {};
    const modeHooks = {};
    vm.runInNewContext(output.outputText, {
      ...sandbox, exports: modeExports,
      process: { ...sandbox.process, env: { ...sandbox.process.env, SIQ_AGENT_SECURITY_MODE: mode } },
    }, { filename: sourcePath });
    modeExports.default.register({ on(name, callback) { modeHooks[name] = callback; } });
    assert.equal((await modeHooks.before_tool_call({ ...event, sessionId: context.sessionId }, { sessionKey: 'session-1' })).block, true,
      'missing native epoch must hard deny even in advisory modes');
    decision = { action: 'hold', action_id: 'act-' + mode, receipt_id: 'rcp-' + mode, reason: 'approval' };
    const queries = statusQueries;
    assert.equal(await modeHooks.before_tool_call({ ...event, toolCallId: mode }, { sessionKey: 'session-1', sessionId: '11111111-1111-4111-8111-111111111111', agentId: 'agent-1' }), undefined);
    assert.equal(statusQueries, queries, 'advisory mode must not enter unsupported platform approval');
  }
  console.log('OpenClaw correlation, host capability and approval recheck gates passed');
  console.log(JSON.stringify({
    schema_version: 'siq.openclaw-business-tool-parity/v1',
    status: 'passed',
    tool: businessTool,
    parameter_names: Object.keys(businessParams).sort(),
    exact_final_params_reserved: true,
    changed_digest_reserved: false,
    approved_observation_uses_reservation: true,
    arbitrary_command_parameter_supported: false,
    arbitrary_path_parameter_supported: false,
  }));
})().catch(error => { console.error(error); process.exitCode = 1; });
