// Isolated hook contract tests; never read the developer's platform config/token.
const assert = require('node:assert/strict');
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
const exportsObject = {};
const sandbox = {
  exports: exportsObject,
  process: { env: { OPENCLAW_STATE_DIR: '/isolated-profile' }, platform: 'linux' },
  console: { warn() {} },
  setTimeout, clearTimeout, AbortController,
  require(name) {
    if (name === 'node:fs') return {
      readFileSync(p) {
        if (p.endsWith('/token')) return 't'.repeat(64);
        configReads.push(p);
        if (p === '/isolated-profile/siq-agent-security.json') return JSON.stringify({ tokenPath: '/isolated-profile/decision/token', holdWaitMs: 500 });
        throw Error('unexpected config location');
      },
      mkdirSync() {}, appendFileSync() {},
    };
    if (name === 'node:os') return { homedir: () => '/isolated-test' };
    if (name === 'node:path') return path;
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
    return { status: 200, json: async () => decision };
  },
};
vm.runInNewContext(output.outputText, sandbox, { filename: sourcePath });
assert.deepEqual(configReads, ['/isolated-profile/siq-agent-security.json'], 'isolated platform state must not read the default user config');
exportsObject.default.register({ on(name, callback) { hooks[name] = callback; } });
(async () => {
  const event = { toolName: 'read_file', toolCallId: 'call-1', params: { path: '/approved/report' }, result: 'ok' };
  const context = { sessionKey: 'session-1', agentId: 'agent-1' };
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
  for (const mode of ['approved', 'pending-then-approved', 'denied', 'expired', 'consumed', 'wrong-action', 'stale', 'invalid-time', 'pending', 'offline']) {
    approvalMode = mode;
    statusQueries = 0;
    decision = { action: 'hold', action_id: 'act-' + mode, receipt_id: 'rcp-' + mode, reason: 'requires local approval', hold: { timeout_ms: 60000 } };
    const result = await hooks.before_tool_call({ ...event, toolCallId: 'hold-' + mode }, context);
    const shouldApprove = mode === 'approved' || mode === 'pending-then-approved';
    assert.equal(!!result.requireApproval, shouldApprove, mode);
    if (shouldApprove) {
      assert.equal(result.requireApproval.timeoutBehavior, 'deny');
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
  console.log('OpenClaw correlation and local approval/denial/expiry/timeout/cancellation gates passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
