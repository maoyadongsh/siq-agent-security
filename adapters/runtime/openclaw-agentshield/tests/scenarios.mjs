// Scenario runner for the OpenClaw plugin. Each scenario is a self-contained
// function executed in its own process (the plugin loads its config once at
// import time), driving the real hook handlers against a mock local decision
// service — the same "requests the plugin would emit" convention as the
// 2026-09-05 OpenClaw evidence, extended with the managed runtime-identity
// flow (M126).
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import assert from "node:assert/strict";
import { register } from "node:module";

const RI = "ri-" + "a".repeat(32);
const AGENT = "hri-" + "b".repeat(32);
const CREDENTIAL = `${RI}.${"c".repeat(64)}`;

function json(res, status, body) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

function makeHome({ managed = true, token = null, agentId = managed ? AGENT : "default", mode = "block" } = {}) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "oc-plugin-"));
  const state = path.join(home, "state");
  fs.mkdirSync(path.join(state, "runtime-identity-secrets"), { recursive: true });
  const tokenPath = managed
    ? path.join(state, "runtime-identity-secrets", `${RI}.token`)
    : path.join(state, "token");
  fs.writeFileSync(tokenPath, token ?? (managed ? CREDENTIAL : "legacy-global-token"));
  const cfg = { endpoint: "placeholder", tokenPath, enforcementMode: mode, agentId };
  if (managed) cfg.runtimeIdentityId = RI;
  fs.writeFileSync(path.join(home, "siq-agent-security.json"), JSON.stringify(cfg));
  return { home, tokenPath };
}

function makeServer(handlers) {
  const requests = [];
  const server = http.createServer((req, res) => {
    res.on("error", () => {}); // aborted client (capture budget) — ignore
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      let parsed = {};
      try { parsed = JSON.parse(body || "{}"); } catch { /* keep {} */ }
      const entry = { url: req.url, auth: req.headers.authorization ?? "", body: parsed };
      requests.push(entry);
      const handler = handlers[req.url];
      if (!handler) { json(res, 404, {}); return; }
      try {
        handler(res, parsed);
      } catch {
        json(res, 500, {});
      }
    });
  });
  return new Promise((resolve) =>
    server.listen(0, "127.0.0.1", () => resolve({ server, requests, port: server.address().port })));
}

function enrolled(session) {
  return {
    schema_version: "local-runtime-session-enrolled/v1",
    identity_id: RI, platform: "openclaw", agent_id: AGENT, session_id: session,
    binding_id: "bind-" + "d".repeat(64), intent_id: "int-ri-" + "e".repeat(64),
    expires_at: new Date(Date.now() + 60_000).toISOString(),
  };
}

function allowHandlers(captureStatus = 201, captureDelayMs = 0) {
  return {
    "/v1/runtime-sessions": (res, body) => json(res, 200, enrolled(body.session_id)),
    "/v1/decide": (res) => json(res, 200, { action: "allow", reason: "ok", receipt_id: "rcp-1", action_id: "act-1" }),
    "/v1/observe": (res) => json(res, 200, {}),
    "/v1/raw-task-content/native-captures": (res) => {
      if (captureDelayMs) setTimeout(() => json(res, captureStatus, {}), captureDelayMs);
      else json(res, captureStatus, {});
    },
  };
}

async function loadPlugin(endpoint) {
  process.env.OPENCLAW_STATE_DIR = process.env.__OC_HOME;
  process.env.SIQ_AGENT_SECURITY_ENDPOINT = endpoint;
  register("./resolve-hook.mjs", import.meta.url);
  await import("../index.ts");
  const handlers = {};
  globalThis.__pluginEntry.register({
    on: (name, fn) => { handlers[name] = fn; },
  });
  return handlers;
}

const before = (handlers, params) => handlers.before_tool_call(
  { toolName: "write_file", toolCallId: "call-1", params, sessionKey: "s1" },
  { sessionKey: "s1", agentId: AGENT },
);
const after = (handlers, result) => handlers.after_tool_call(
  { toolName: "write_file", toolCallId: "call-1", params: {}, result, sessionKey: "s1" },
  { sessionKey: "s1", agentId: AGENT },
);

const scenarios = {
  // Legacy (non-managed) behavior is unchanged: no enrollment, no captures.
  async "legacy-no-enrollment-no-capture"() {
    const { home } = makeHome({ managed: false });
    process.env.__OC_HOME = home;
    const { server, requests, port } = await makeServer(allowHandlers());
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    assert.equal(await before(handlers, { path: "/tmp/x" }), undefined);
    await after(handlers, "done");
    assert.deepEqual(requests.map((r) => r.url), ["/v1/decide", "/v1/observe"]);
    assert.equal(requests[0].auth, "Bearer legacy-global-token");
    server.close();
  },

  // Managed allow: enroll → decide → parameters capture with JSON-pointer fields.
  async "managed-allow-enrolls-and-captures-params"() {
    const { home } = makeHome({});
    process.env.__OC_HOME = home;
    const { server, requests, port } = await makeServer(allowHandlers());
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    assert.equal(await before(handlers, { path: "/work/public/report", content: "hello" }), undefined);
    assert.deepEqual(requests.map((r) => r.url),
      ["/v1/runtime-sessions", "/v1/decide", "/v1/raw-task-content/native-captures"]);
    const enroll = requests[0];
    assert.equal(enroll.auth, `Bearer ${CREDENTIAL}`);
    assert.equal(enroll.body.schema_version, "local-runtime-session-enroll/v1");
    assert.equal(enroll.body.session_id, "s1");
    const decide = requests[1];
    assert.equal(decide.body.platform, "openclaw");
    assert.equal(decide.body.agent_id, AGENT);
    assert.equal(decide.body.session_id, "s1");
    const capture = requests[2];
    assert.equal(capture.body.schema_version, "local-raw-task-content-native-capture/v1");
    assert.equal(capture.body.platform, "openclaw");
    assert.equal(capture.body.agent_id, AGENT);
    assert.equal(capture.body.session_id, "s1");
    assert.equal(capture.body.kind, "parameters");
    assert.ok(capture.body.fields.some((f) => f.path === "/tool/name" && f.value === "write_file"));
    assert.ok(capture.body.fields.some((f) => f.path === "/tool/arguments/path" && f.value === '"/work/public/report"'));
    server.close();
  },

  // Enrollment failure fails closed in block mode and never reaches decide.
  async "managed-enroll-failure-fails-closed"() {
    const { home } = makeHome({});
    process.env.__OC_HOME = home;
    const handlers0 = allowHandlers();
    handlers0["/v1/runtime-sessions"] = (res) => json(res, 500, {});
    const { server, requests, port } = await makeServer(handlers0);
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    const outcome = await before(handlers, { path: "/tmp/x" });
    assert.equal(outcome.block, true);
    assert.match(outcome.blockReason, /fail-closed/);
    assert.deepEqual(requests.map((r) => r.url), ["/v1/runtime-sessions"]);
    server.close();
  },

  // A foreign-platform enrollment response is rejected like a malformed one.
  async "managed-foreign-platform-enrollment-rejected"() {
    const { home } = makeHome({});
    process.env.__OC_HOME = home;
    const handlers0 = allowHandlers();
    handlers0["/v1/runtime-sessions"] = (res, body) => json(res, 200, { ...enrolled(body.session_id), platform: "hermes" });
    const { server, requests, port } = await makeServer(handlers0);
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    assert.equal((await before(handlers, { path: "/tmp/x" })).block, true);
    assert.deepEqual(requests.map((r) => r.url), ["/v1/runtime-sessions"]);
    server.close();
  },

  // A legacy global token must not act as the managed credential.
  async "managed-legacy-token-rejected"() {
    const { home } = makeHome({ token: "legacy-global-token" });
    process.env.__OC_HOME = home;
    const { server, requests, port } = await makeServer(allowHandlers());
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    assert.equal((await before(handlers, { path: "/tmp/x" })).block, true);
    assert.deepEqual(requests, []);
    server.close();
  },

  // Observed result of an allowed call carries the decision reference and an
  // output capture rooted at /tool/result.
  async "managed-observe-with-reference-captures-output"() {
    const { home } = makeHome({});
    process.env.__OC_HOME = home;
    const { server, requests, port } = await makeServer(allowHandlers());
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    assert.equal(await before(handlers, { path: "/work/public/report" }), undefined);
    await after(handlers, { report: "done" });
    const observe = requests.find((r) => r.url === "/v1/observe");
    assert.equal(observe.body.action_id, "act-1");
    assert.equal(observe.body.decision_receipt_id, "rcp-1");
    const captures = requests.filter((r) => r.url === "/v1/raw-task-content/native-captures");
    assert.equal(captures.length, 2);
    assert.equal(captures[1].body.kind, "output");
    assert.ok(captures[1].body.fields.some((f) => f.path === "/tool/result/report" && f.value === '"done"'));
    server.close();
  },

  // Real-host regression (M127): OpenClaw tool-result carriers carry
  // undefined function-slot fields (details/terminate). A capture must skip
  // those leaves instead of aborting the whole output record.
  async "managed-output-capture-skips-undefined-leaves"() {
    const { home } = makeHome({});
    process.env.__OC_HOME = home;
    const { server, requests, port } = await makeServer(allowHandlers());
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    assert.equal(await before(handlers, { path: "/work/public/report" }), undefined);
    const carrier = { content: [{ type: "text", text: "fixture-visible-company-a" }], details: undefined, terminate: undefined };
    await after(handlers, carrier);
    const captures = requests.filter((r) => r.url === "/v1/raw-task-content/native-captures");
    assert.equal(captures.length, 2);
    assert.equal(captures[1].body.kind, "output");
    assert.ok(captures[1].body.fields.some((f) => f.path === "/tool/result/content/0/text" && f.value === '"fixture-visible-company-a"'));
    assert.ok(!captures[1].body.fields.some((f) => f.path.includes("details") || f.path.includes("terminate")));
    server.close();
  },

  // The 250 ms capture budget is best effort: a slow daemon must not block
  // the allow path or the hook.
  async "managed-capture-timeout-is-best-effort"() {
    const { home } = makeHome({});
    process.env.__OC_HOME = home;
    const { server, requests, port } = await makeServer(allowHandlers(201, 1500));
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    assert.equal(await before(handlers, { path: "/tmp/x" }), undefined);
    assert.ok(requests.some((r) => r.url === "/v1/decide"));
    server.close();
  },

  // Managed deny mapping is unchanged by the managed prelude.
  async "managed-deny-blocks-with-receipt"() {
    const { home } = makeHome({});
    process.env.__OC_HOME = home;
    const handlers0 = allowHandlers();
    handlers0["/v1/decide"] = (res) => json(res, 200, { action: "deny", reason: "not granted", receipt_id: "rcp-2" });
    const { server, requests, port } = await makeServer(handlers0);
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    const outcome = await before(handlers, { path: "/tmp/x" });
    assert.equal(outcome.block, true);
    assert.match(outcome.blockReason, /denied/);
    assert.match(outcome.blockReason, /rcp-2/);
    assert.deepEqual(requests.map((r) => r.url), ["/v1/runtime-sessions", "/v1/decide"]);
    server.close();
  },
  // Real-host regression (M127): OpenClaw supplies ctx.agentId (its own agent
  // id). In managed mode the session is bound to the pinned instance agent, so
  // the plugin must report cfg.agentId regardless of the host value.
  async "managed-ignores-host-agent-id"() {
    const { home } = makeHome({});
    process.env.__OC_HOME = home;
    const { server, requests, port } = await makeServer(allowHandlers());
    const handlers = await loadPlugin(`http://127.0.0.1:${port}`);
    const hostCtx = { sessionKey: "s1", agentId: "intent-v2-fixture-agent" };
    assert.equal(
      await handlers.before_tool_call(
        { toolName: "read", toolCallId: "call-9", params: { path: "/work/r" }, sessionKey: "s1" },
        hostCtx,
      ),
      undefined,
    );
    await handlers.after_tool_call(
      { toolName: "read", toolCallId: "call-9", params: { path: "/work/r" }, result: "ok", sessionKey: "s1" },
      hostCtx,
    );
    for (const request of requests) {
      // The enroll request body intentionally carries only schema_version and
      // session_id; the agent pin applies to decide and observe payloads.
      if (request.url === "/v1/runtime-sessions") continue;
      assert.equal(request.body.agent_id, AGENT, `agent pin violated on ${request.url}`);
    }
    server.close();
  },
};

for (const mode of ["block", "warn", "audit_only"]) {
  for (const failure of ["enroll", "decide", "missing-reference", "bad-identity", "bad-config", "no-session", "remote", "credentials-url", "query-url", "redirect", "expired"]) {
    scenarios[`boundary-${mode}-${failure}`] = async () => {
      const { home } = makeHome({ mode });
      process.env.__OC_HOME = home;
      const configPath = path.join(home, "siq-agent-security.json");
      if (failure === "bad-config") fs.writeFileSync(configPath, "{");
      if (failure === "bad-identity") {
        const config = JSON.parse(fs.readFileSync(configPath));
        config.runtimeIdentityId = "invalid";
        config.agentId = "default";
        fs.writeFileSync(configPath, JSON.stringify(config));
      }
      const routes = allowHandlers();
      if (failure === "enroll" || failure === "decide") routes[`/v1/${failure === "enroll" ? "runtime-sessions" : "decide"}`] = res => json(res, 503, {});
      if (failure === "missing-reference") routes["/v1/decide"] = res => json(res, 200, { action: "allow", receipt_id: "r", reason: "ok" });
      if (failure === "expired") routes["/v1/runtime-sessions"] = (res, body) => json(res, 200, { ...enrolled(body.session_id), expires_at: "2000-01-01T00:00:00Z" });
      const { server, requests, port } = await makeServer(routes);
      try {
        if (failure === "redirect") routes["/v1/runtime-sessions"] = res => {
          res.writeHead(307, { location: `http://127.0.0.1:${port}/credential-trap` }); res.end();
        };
        let endpoint = `http://127.0.0.1:${port}`;
        if (failure === "remote") endpoint = `http://192.0.2.1:${port}`;
        if (failure === "credentials-url") endpoint = `http://user:password@127.0.0.1:${port}`;
        if (failure === "query-url") endpoint += "?trap=1";
        const handlers = await loadPlugin(endpoint);
        const outcome = failure === "no-session"
          ? await handlers.before_tool_call({ toolName: "read", toolCallId: "c", params: {} }, {})
          : await before(handlers, {});
        assert.equal(outcome?.block, true);
        assert.ok(!requests.some(r => r.url === "/credential-trap" || r.url === "/v1/raw-task-content/native-captures"));
        if (["remote", "credentials-url", "query-url", "bad-config", "bad-identity", "no-session"].includes(failure)) assert.equal(requests.length, 0);
      } finally { server.close(); fs.rmSync(home, { recursive: true, force: true }); }
    };
  }
}

for (const flow of [
  "duplicate-post",
  "duplicate-pre",
  "blocked-hold",
  "approved-hold",
  "reserve-rejected",
  "reserve-malformed",
  "reserve-response-loss",
]) {
  scenarios[`correlation-${flow}`] = async () => {
    const { home } = makeHome(); process.env.__OC_HOME = home;
    const routes = allowHandlers();
    const held = ["blocked-hold", "approved-hold", "reserve-rejected", "reserve-malformed", "reserve-response-loss"].includes(flow);
    if (held) {
      routes["/v1/decide"] = res => json(res, 200, { action: "hold", reason: "approve", receipt_id: "rcp-1", action_id: "act-1" });
      routes["/v1/hold-status"] = res => json(res, 200, {
        schema_version: "hold-status/v1", action_id: "act-1", decision_receipt_id: "rcp-1",
        status: "approved", reason_code: "hold_approved", expires_at: new Date(Date.now() + 60000).toISOString(),
      });
      routes["/v1/hold-executions/reserve"] = (res, body) => {
        if (flow === "reserve-rejected") return json(res, 409, {});
        if (flow === "reserve-response-loss") return res.destroy();
        return json(res, 201, {
          schema_version: "hold-execution-status/v1",
          status: "reserved",
          action_id: body.action_id,
          decision_receipt_id: body.decision_receipt_id,
          reservation_receipt_id: flow === "reserve-malformed" ? "" : `${body.decision_receipt_id}-exec`,
          expires_at: new Date(Date.now() + 60000).toISOString(),
          reason_code: "hold_execution_reserved",
        });
      };
    }
    const { server, requests, port } = await makeServer(routes);
    try {
      const handlers = await loadPlugin(`http://localhost:${port}`);
      const decision = await handlers.before_tool_call(
        { toolName: "write_file", toolCallId: "call-1", params: {}, sessionKey: "s1" },
        {
          sessionKey: "s1",
          approvalExecutionRecheckVersion:
            flow === "approved-hold" || flow.startsWith("reserve-") ? 1 : undefined,
        });
      if (flow === "duplicate-pre") assert.equal((await before(handlers, {})).block, true);
      if (flow === "blocked-hold") assert.equal(decision.block, true);
      if (flow === "approved-hold") {
        assert.equal(await decision.requireApproval.beforeExecute({}), true);
        const reserve = requests.find(r => r.url === "/v1/hold-executions/reserve");
        assert.equal(reserve.body.original_tool_call_id, "call-1");
        assert.notEqual(reserve.body.retry_tool_call_id, "call-1");
      }
      if (flow.startsWith("reserve-")) {
        assert.equal(await decision.requireApproval.beforeExecute({}), false);
        assert.equal(requests.filter(r => r.url === "/v1/hold-executions/reserve").length, 1);
        return;
      }
      await after(handlers, "result");
      await after(handlers, "duplicate result");
      const output = requests.filter(r => r.url === "/v1/raw-task-content/native-captures" && r.body.kind === "output");
      assert.equal(output.length, ["duplicate-post", "approved-hold"].includes(flow) ? 1 : 0);
      if (flow === "approved-hold") {
        const reserve = requests.find(r => r.url === "/v1/hold-executions/reserve");
        const observe = requests.find(r => r.url === "/v1/observe");
        assert.equal(observe.body.tool_call_id, reserve.body.retry_tool_call_id);
        assert.equal(observe.body.decision_receipt_id, "rcp-1-exec");
      }
      assert.equal((await before(handlers, {})).block, true, "consumed call must remain unusable");
    } finally { server.close(); fs.rmSync(home, { recursive: true, force: true }); }
  };
}

const name = process.argv[2];
if (!scenarios[name]) {
  console.error(`unknown scenario: ${name}`);
  process.exit(2);
}
try {
  await scenarios[name]();
  console.log(`OK ${name}`);
} catch (error) {
  console.error(error);
  process.exit(1);
}
