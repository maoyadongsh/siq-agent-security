// Installed OpenClaw loader, execution wrapper and after-tool relay. No mocks.
// The parent supplies an isolated state/config directory and synthetic files.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";

const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const dist = path.join(spec.openclaw_root, "dist");
const sources = {};
const digest = (file) => createHash("sha256").update(fs.readFileSync(file)).digest("hex");
async function importFile(file) {
  sources[path.relative(spec.openclaw_root, file)] = digest(file);
  return import(pathToFileURL(file).href);
}

// OpenClaw ships hashed internal chunks. Select the actual exported runtime
// function, refusing versions that do not expose the expected implementation.
async function nativeFunction(prefix, name) {
  const files = fs.readdirSync(dist).filter((file) => file.startsWith(prefix) && file.endsWith(".js"));
  const matches = files.filter((file) => fs.readFileSync(path.join(dist, file), "utf8").includes(`function ${name}(`));
  assert.equal(matches.length, 1, `unsupported native runtime export: ${name}`);
  const file = path.join(dist, matches[0]);
  const source = fs.readFileSync(file, "utf8");
  const alias = source.match(new RegExp(`\\b${name} as (\\w+)`));
  const module = await importFile(file);
  const fn = module[alias?.[1] ?? name];
  assert.equal(typeof fn, "function", `native export unavailable: ${name}`);
  return fn;
}

const config = JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH, "utf8"));
const { loadOpenClawPlugins } = await importFile(path.join(dist, "plugins/loader.js"));
const registry = loadOpenClawPlugins({
  config, workspaceDir: spec.workspace, cache: false, activate: true,
  onlyPluginIds: ["siq-agent-security"], throwOnLoadError: true,
  logger: { info() {}, warn() {}, error() {}, debug() {} },
});
assert.ok(registry.plugins.some((p) => p.id === "siq-agent-security" && p.status === "loaded"), "SIQ native plugin was not loaded");
const wrap = await nativeFunction("pi-tools.before-tool-call-", "wrapToolWithBeforeToolCallHook");
const after = await nativeFunction("native-hook-relay-", "runAgentHarnessAfterToolCallHook");
const coding = await importFile(path.join(spec.openclaw_root, "node_modules/@earendil-works/pi-coding-agent/dist/index.js"));
const tools = { read: coding.createReadTool(spec.workspace), write: coding.createWriteTool(spec.workspace) };
const outputs = [];
for (const call of spec.calls) {
  assert.ok(tools[call.tool], "only fixture file tools may execute");
  const context = { config, cwd: spec.workspace, agentId: spec.agent_id,
    sessionKey: call.session_id ?? spec.session_id, sessionId: call.session_id ?? spec.session_id,
    runId: "native-fixture-run", loopDetection: { enabled: false } };
  const tool = wrap(tools[call.tool], context);
  const result = await tool.execute(call.id, call.params);
  if (result?.details?.status !== "blocked") {
    await after({ ...context, toolName: tool.name, toolCallId: call.id,
      startArgs: call.params, result });
  }
  outputs.push({ id: call.id, result: JSON.stringify(result) });
}
fs.writeFileSync(spec.result_path, JSON.stringify({ outputs, sources,
  openclaw_version: JSON.parse(fs.readFileSync(path.join(spec.openclaw_root, "package.json"))).version }));
