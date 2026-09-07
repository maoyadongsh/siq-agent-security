// Native gateway/RPC reset against synthetic sessions in an isolated state root.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";

const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const sources = {};
const dist = path.join(spec.openclaw_root, "dist");
async function nativeFunction(prefix, name) {
  const matches = fs.readdirSync(dist).filter((file) => file.startsWith(prefix) && file.endsWith(".js") &&
    fs.readFileSync(path.join(dist, file), "utf8").includes(`function ${name}(`));
  assert.equal(matches.length, 1, `unsupported native export: ${name}`);
  const file = path.join(dist, matches[0]);
  const source = fs.readFileSync(file, "utf8");
  sources[`dist/${matches[0]}`] = createHash("sha256").update(source).digest("hex");
  const alias = source.match(new RegExp(`\\b${name} as (\\w+)`));
  const module = await import(pathToFileURL(file).href);
  const fn = module[alias?.[1] ?? name];
  assert.equal(typeof fn, "function");
  return fn;
}

let gateway;
try {
  const config = JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH, "utf8"));
  const start = await nativeFunction("server-", "startGatewayServer");
  // Fingerprint the implementation and reset service; invoke reset only via RPC.
  await nativeFunction("server.impl-", "startGatewayServer");
  await nativeFunction("session-reset-service-", "performGatewaySessionReset");
  gateway = await start(spec.port, { bind: "loopback", controlUiEnabled: false });
  const call = await nativeFunction("call-", "callGateway");
  const entry = () => JSON.parse(fs.readFileSync(spec.session_store, "utf8"))[spec.session_key];
  assert.equal(entry().sessionId, spec.previous_id);
  const oldTranscript = entry().sessionFile;
  assert.equal(typeof oldTranscript, "string", "native transcript path missing");
  const oldTranscriptHash = createHash("sha256").update(fs.readFileSync(oldTranscript)).digest("hex");
  const archiveNames = () => fs.readdirSync(path.dirname(oldTranscript))
    .filter((name) => name.startsWith(path.basename(oldTranscript) + ".reset."));
  const previousArchives = new Set(archiveNames());
  const before = createHash("sha256").update(fs.readFileSync(spec.session_store)).digest("hex");
  const options = { url: `ws://127.0.0.1:${spec.port}`, token: config.gateway.auth.token,
    method: "sessions.reset", params: { key: spec.session_key, reason: "reset" },
    timeoutMs: 15000, clientName: "gateway-client", mode: "backend" };
  let readonlyRejected = false;
  try { await call({ ...options, scopes: ["operator.read"] }); }
  catch (error) {
    assert.match(error.message, /missing scope/i, "read-only reset failed for an unexpected reason");
    readonlyRejected = true;
  }
  assert.ok(readonlyRejected, "read-only client reset the session");
  assert.equal(createHash("sha256").update(fs.readFileSync(spec.session_store)).digest("hex"), before,
    "rejected reset changed session store");
  const response = await call({ ...options, scopes: ["operator.admin"] });
  assert.equal(response.ok, true);
  assert.equal(response.key, spec.session_key);
  assert.notEqual(response.entry.sessionId, spec.previous_id);
  assert.equal(entry().sessionId, response.entry.sessionId);
  const newHeaderLines = fs.readFileSync(entry().sessionFile, "utf8").trim().split("\n");
  assert.equal(newHeaderLines.length, 1, "reset transcript contains old messages");
  const header = JSON.parse(newHeaderLines[0]);
  assert.equal(header.type, "session");
  assert.equal(header.id, response.entry.sessionId, "reset transcript header has wrong UUID");
  const newArchives = archiveNames().filter((name) => !previousArchives.has(name));
  assert.equal(newArchives.length, 1, "old transcript was not uniquely archived");
  assert.equal(createHash("sha256").update(fs.readFileSync(path.join(path.dirname(oldTranscript), newArchives[0]))).digest("hex"), oldTranscriptHash,
    "reset archive did not preserve the old transcript bytes");
  fs.writeFileSync(spec.result_path, JSON.stringify({ method: "sessions.reset",
    readonly_reset_rejected: readonlyRejected, rejected_reset_store_unchanged: true,
    fresh_header_matches_new_uuid: true, old_transcript_archived_unchanged: true,
    reset_succeeded: true, native_uuid_after_rpc: response.entry.sessionId, sources }), { mode: 0o600 });
} finally {
  await gateway?.close({ reason: "synthetic gateway reset fixture complete" });
}
