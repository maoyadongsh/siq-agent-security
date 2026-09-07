// Native gateway + operator WebSocket + tool wrapper; only the tool is synthetic.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";

const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const sources = {};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function write(name, data) {
  const target = path.join(spec.control_dir, name);
  fs.writeFileSync(target + ".tmp", JSON.stringify(data), { mode: 0o600 });
  fs.renameSync(target + ".tmp", target);
}
async function nativeFunction(prefix, name) {
  const dist = path.join(spec.openclaw_root, "dist");
  const matches = fs.readdirSync(dist).filter((file) => file.startsWith(prefix) && file.endsWith(".js") &&
    fs.readFileSync(path.join(dist, file), "utf8").includes(`function ${name}(`));
  assert.equal(matches.length, 1, `unsupported native export: ${name}`);
  const file = path.join(dist, matches[0]);
  const source = fs.readFileSync(file, "utf8");
  sources[path.relative(spec.openclaw_root, file)] = createHash("sha256").update(source).digest("hex");
  const module = await import(pathToFileURL(file).href);
  const alias = source.match(new RegExp(`\\b${name} as (\\w+)`));
  const fn = module[alias?.[1] ?? name];
  assert.equal(typeof fn, "function", `missing native function: ${name}`);
  return fn;
}

let gateway, operator;
let stage = "startup";
try {
  const config = JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH, "utf8"));
  const startGateway = await nativeFunction("server-", "startGatewayServer");
  // Fingerprint the actual gateway implementation and approval handlers, not
  // just the lazy exported entry. This is a selected-source record, not a
  // complete module-load trace.
  for (const [prefix, symbol] of [["server.impl-", "startGatewayServer"],
    ["plugin-approval-", "createPluginApprovalHandlers"],
    ["approval-shared-", "handlePendingApprovalRequest"],
    ["server-request-context-", "createGatewayRequestContext"]]) {
    const files = fs.readdirSync(path.join(spec.openclaw_root, "dist"))
      .filter((file) => file.startsWith(prefix) && file.endsWith(".js") &&
        fs.readFileSync(path.join(spec.openclaw_root, "dist", file), "utf8").includes(`function ${symbol}(`));
    assert.equal(files.length, 1, `unsupported runtime source: ${prefix}`);
    const relative = `dist/${files[0]}`;
    sources[relative] = createHash("sha256").update(fs.readFileSync(path.join(spec.openclaw_root, relative))).digest("hex");
  }
  gateway = await startGateway(spec.port, { bind: "loopback", controlUiEnabled: false });
  const createOperator = await nativeFunction("operator-approvals-client-", "createOperatorApprovalsGatewayClient");
  let ready, connectError;
  const connected = new Promise((resolve, reject) => { ready = resolve; connectError = reject; });
  const requests = new Map();
  operator = await createOperator({ config, clientDisplayName: "synthetic-fixture-operator",
    onHelloOk: ready, onConnectError: connectError,
    onEvent(event) {
      if (event.event !== "plugin.approval.requested") return;
      const payload = event.payload;
      const id = payload?.request?.toolCallId;
      assert.ok(spec.cases.some((entry) => entry.id === id), "unexpected approval request");
      assert.ok(!requests.has(id), "duplicate native approval request");
      requests.set(id, payload.id);
      write(`${id}.request.json`, { id: payload.id, tool_call_id: id, received_at: Date.now() });
    },
  });
  operator.start();
  await Promise.race([connected, sleep(15000).then(() => { throw new Error("operator readiness timeout"); })]);
  stage = "plugin-loader";
  const loaderPath = path.join(spec.openclaw_root, "dist/plugins/loader.js");
  sources["dist/plugins/loader.js"] = createHash("sha256").update(fs.readFileSync(loaderPath)).digest("hex");
  const { loadOpenClawPlugins } = await import(pathToFileURL(loaderPath).href);
  const registry = loadOpenClawPlugins({ config, workspaceDir: spec.workspace,
    cache: false, activate: true, onlyPluginIds: ["siq-agent-security"], throwOnLoadError: true,
    logger: { info() {}, warn() {}, error() {}, debug() {} },
  });
  assert.ok(registry.plugins.some((plugin) => plugin.id === "siq-agent-security" && plugin.status === "loaded"), "SIQ native plugin not loaded");
  stage = "wrapper";
  const wrap = await nativeFunction("pi-tools.before-tool-call-", "wrapToolWithBeforeToolCallHook");
  const after = await nativeFunction("native-hook-relay-", "runAgentHarnessAfterToolCallHook");
  const context = { config, cwd: spec.workspace, agentId: spec.agent_id,
    sessionKey: spec.session_id, sessionId: spec.session_id,
    runId: "native-approval-fixture", loopDetection: { enabled: false } };
  const outputs = [];
  for (const entry of spec.cases) {
    stage = entry.id;
    const marker = path.join(spec.control_dir, `${entry.id}.executed.json`);
    const tool = wrap({ name: "exec", label: "Synthetic execution marker", description: "Fixture only",
      parameters: { type: "object", properties: { command: { type: "string" } } },
      async execute(callId, params) {
        assert.equal(callId, entry.id);
        assert.deepEqual(params, { command: "printf fixture" });
        write(`${entry.id}.executed.json`, { executed_at: Date.now() });
        return { content: [{ type: "text", text: "synthetic fixture result" }], details: {} };
      },
    }, context);
    const cancellation = new AbortController();
    const execution = tool.execute(entry.id, { command: "printf fixture" }, cancellation.signal);
    let settled = false;
    execution.then(() => { settled = true; }, () => { settled = true; });
    // Register rejection immediately while waiting for the real gateway event.
    execution.catch(() => {});
    const choicePath = path.join(spec.control_dir, `${entry.id}.choice.json`);
    const deadline = Date.now() + 25000;
    while (!settled && !fs.existsSync(choicePath)) {
      assert.ok(Date.now() < deadline, "operator choice timeout");
      await sleep(25);
    }
    let choice = { decision: null };
    if (fs.existsSync(choicePath)) {
      assert.ok(requests.has(entry.id), "no native gateway approval request");
      choice = JSON.parse(fs.readFileSync(choicePath, "utf8"));
      if (choice.decision === "cancel") cancellation.abort(new Error("fixture cancellation"));
      else {
        assert.ok(["deny", "allow-once"].includes(choice.decision));
        await operator.request("plugin.approval.resolve", { id: requests.get(entry.id), decision: choice.decision });
      }
    } else assert.ok(!requests.has(entry.id), "platform approval started before local approval");
    let result;
    try {
      result = await execution;
    } catch (error) {
      assert.ok(["deny", "cancel"].includes(choice.decision), "unexpected native rejection");
      assert.equal(error.message, choice.decision === "deny" ? "Denied by user" : "Approval cancelled (run aborted)");
      assert.ok(!fs.existsSync(marker), "denied tool executed before raising");
      result = { details: { status: "blocked" } };
    }
    const executed = fs.existsSync(marker);
    // The native cancellation race leaves its gateway wait RPC pending. Once
    // execution has settled as cancelled, the synthetic operator closes that
    // pending request with deny so fixture shutdown does not wait for its TTL.
    if (choice.decision === "cancel") {
      assert.ok(!executed, "cancelled execution ran");
      await operator.request("plugin.approval.resolve", { id: requests.get(entry.id), decision: "deny" });
    }
    if (executed) await after({ ...context, toolName: "exec", toolCallId: entry.id,
      startArgs: { command: "printf fixture" }, result });
    const output = { id: entry.id, executed, platform_decision: choice.decision, platform_requested: requests.has(entry.id),
      cancelled_request_cleanup: choice.decision === "cancel",
      blocked: result?.details?.status === "blocked" };
    outputs.push(output);
    write(`${entry.id}.done.json`, output);
  }
  write("result.json", { outputs, sources,
    openclaw_version: JSON.parse(fs.readFileSync(path.join(spec.openclaw_root, "package.json"), "utf8")).version });
} catch (error) {
  // Raw runtime logs stay in the parent's private capture; no tokens in artifacts.
  write("error.json", { stage, category: error?.constructor?.name ?? "Error" });
  throw error;
} finally {
  await operator?.stopAndWait().catch(() => operator.stop());
  await gateway?.close({ reason: "synthetic fixture complete" });
}
