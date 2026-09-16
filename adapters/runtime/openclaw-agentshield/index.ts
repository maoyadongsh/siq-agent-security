/**
 * OpenClaw runtime adapter for siq-agent-security (dev-spec §4.1).
 *
 * Thin by contract: maps `before_tool_call` / `after_tool_call` to the local
 * decision API (127.0.0.1, bearer token read once from the state
 * directory). Holds no rules, no policy and no signing key.
 *
 * Decision mapping:
 *   allow  → undefined (no decision)
 *   deny   → { block: true, blockReason }
 *   hold   → local + native approval, then atomically reserve one execution
 *   redact → { params }  (host-owned params rewritten with secrets removed)
 *
 * Fail-closed table (§3.8.4): in `block` mode an unreachable / timed-out / 401 /
 * malformed service blocks the call; in `audit_only` / `warn` it allows and logs.
 * OpenClaw's own 15 s policy-hook timeout fails closed as the outer guard.
 *
 * Config: ~/.openclaw/siq-agent-security.json (legacy agentshield.json still read)
 *   { "endpoint": "http://127.0.0.1:47611", "tokenPath": "<state>/token",
 *     "enforcementMode": "block", "timeoutMs": 5000, "agentId": "default" }
 *
 * Managed runtime identity (written by the managed installer; camelCase keys):
 *   { "runtimeIdentityId": "ri-<32hex>", "agentId": "hri-<32hex>",
 *     "tokenPath": "<state>/runtime-identity-secrets/ri-<32hex>.token" }
 * In managed mode the credential file must hold "ri-<32hex>.<64hex>" matching
 * runtimeIdentityId, every session is enrolled via /v1/runtime-sessions before
 * the first decide, and allowed calls plus their observed results are offered
 * to /v1/raw-task-content/native-captures (the daemon decides whether raw
 * content is actually stored; the adapter never sees raw-content settings).
 */
import { appendFileSync, closeSync, constants, fstatSync, lstatSync, mkdirSync, openSync, readFileSync, readSync } from "node:fs";
import { createHash } from "node:crypto";
import { homedir } from "node:os";
import { join } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

type Mode = "audit_only" | "warn" | "block";

interface Config {
  endpoint: string;
  tokenPath: string;
  enforcementMode: Mode;
  timeoutMs: number;
  holdWaitMs: number;
  agentId: string;
  runtimeIdentityId?: string;
  configError?: boolean;
}

const RUNTIME_ID_RE = /^ri-[a-f0-9]{32}$/;
const AGENT_ID_RE = /^hri-[a-f0-9]{32}$/;
const MANAGED_TOKEN_RE = /^ri-[a-f0-9]{32}\.[a-f0-9]{64}$/;

interface Decision {
  action: "allow" | "deny" | "hold" | "redact";
  reason: string;
  receipt_id: string;
  action_id?: string;
  task_id?: string;
  runtime_task_id?: string;
  params?: Record<string, unknown>;
  hold?: { channel: string; timeout_ms: number };
}

interface HoldExecutionReservation {
  schema_version: "hold-execution-status/v1";
  status: "reserved";
  action_id: string;
  decision_receipt_id: string;
  reservation_receipt_id: string;
  expires_at: string;
  reason_code: "hold_execution_reserved";
}

function env(...keys: string[]): string {
  for (const k of keys) {
    const v = process.env[k]?.trim();
    if (v) return v;
  }
  return "";
}

function stateDir(): string {
  const fromEnv = env("SIQ_AGENT_SECURITY_STATE_DIR", "AGENTSHIELD_STATE_DIR");
  if (fromEnv) return fromEnv;
  const home = homedir();
  if (process.platform === "darwin") return join(home, "Library", "Application Support", "siq-agent-security");
  if (process.platform === "win32") return join(process.env.LOCALAPPDATA ?? join(home, "AppData", "Local"), "siq-agent-security");
  return join(process.env.XDG_STATE_HOME ?? join(home, ".local", "state"), "siq-agent-security");
}

function loadConfig(): Config {
  const cfg: Config = {
    endpoint: "http://127.0.0.1:47611",
    tokenPath: join(stateDir(), "token"),
    enforcementMode: "block",
    timeoutMs: 5000,
    holdWaitMs: 10000,
    agentId: env("SIQ_AGENT_SECURITY_AGENT_ID", "AGENTSHIELD_AGENT_ID") || "default",
  };
  const configDir = env("OPENCLAW_STATE_DIR") || join(homedir(), ".openclaw");
  for (const name of ["siq-agent-security.json", "agentshield.json"]) {
    try {
      const parsed = JSON.parse(readFileSync(join(configDir, name), "utf8"));
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("invalid config");
      Object.assign(cfg, parsed);
      break;
    } catch (error) {
      if ((error as { code?: string }).code === "ENOENT") continue;
      cfg.configError = true;
      break; // An unreadable or malformed installed config never falls back.
    }
  }
  const endpoint = env("SIQ_AGENT_SECURITY_ENDPOINT", "AGENTSHIELD_ENDPOINT");
  if (endpoint) cfg.endpoint = endpoint;
  const mode = env("SIQ_AGENT_SECURITY_MODE", "AGENTSHIELD_MODE");
  if (mode) cfg.enforcementMode = mode as Mode;
  if (!["block", "warn", "audit_only"].includes(cfg.enforcementMode)) cfg.configError = true;
  if (!Number.isInteger(cfg.timeoutMs) || cfg.timeoutMs < 100 || cfg.timeoutMs > 10000) cfg.configError = true;
  if (!Number.isInteger(cfg.holdWaitMs) || cfg.holdWaitMs < 100 || cfg.holdWaitMs > 10000) cfg.holdWaitMs = 10000;
  return cfg;
}

const cfg = loadConfig();
let token: string | null = null;

function managed(): boolean {
  return cfg.runtimeIdentityId !== undefined || String(cfg.agentId).startsWith("hri-");
}

function localEndpoint(): string | null {
  try {
    const url = new URL(cfg.endpoint);
    if (url.protocol !== "http:" || !url.port || url.username || url.password ||
      url.search || url.hash || url.pathname !== "/" ||
      !["127.0.0.1", "[::1]", "localhost"].includes(url.hostname)) return null;
    if (url.hostname === "localhost") url.hostname = "127.0.0.1";
    return url.origin;
  } catch { return null; }
}

function readToken(): string | null {
  if (token === null) {
    try {
      const info = lstatSync(cfg.tokenPath);
      if (!info.isFile() || info.size > 512) throw new Error("invalid credential file");
      const fd = openSync(cfg.tokenPath, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
      try {
        const actual = fstatSync(fd);
        if (!actual.isFile() || actual.size > 512 || actual.ino !== info.ino || actual.dev !== info.dev) throw new Error("credential changed");
        const bytes = Buffer.alloc(513);
        const count = readSync(fd, bytes, 0, bytes.length, 0);
        token = count <= 512 ? bytes.subarray(0, count).toString("utf8").trim() : "";
      } finally { closeSync(fd); }
    } catch {
      token = "";
    }
    if (managed() && !(MANAGED_TOKEN_RE.test(token) && token.startsWith((cfg.runtimeIdentityId ?? "") + "."))) {
      token = ""; // A legacy global token must not silently act as the managed identity.
    }
  }
  return token || null;
}

async function post<T>(
  path: string, body: unknown, signal?: AbortSignal, remainingMs?: number, expected = 200,
): Promise<T | null> {
  const endpoint = localEndpoint();
  if (signal?.aborted || cfg.configError || !endpoint) return null;
  const tok = readToken();
  if (!tok) return null;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), Math.min(cfg.timeoutMs, remainingMs ?? cfg.timeoutMs));
  const abort = () => ctrl.abort();
  signal?.addEventListener("abort", abort, { once: true });
  try {
    const res = await fetch(endpoint + path, {
      method: "POST",
      redirect: "error",
      headers: { "content-type": "application/json", authorization: `Bearer ${tok}` },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (res.status !== expected) return null;
    const data = (await res.json()) as T;
    return data && typeof data === "object" ? data : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

function pause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => { clearTimeout(timer); signal?.removeEventListener("abort", finish); resolve(); };
    const timer = setTimeout(finish, ms);
    signal?.addEventListener("abort", finish, { once: true });
    if (signal?.aborted) finish();
  });
}

async function waitForLocalApproval(decision: Decision, call: Record<string, unknown>, hookDeadline: number, signal?: AbortSignal) {
  if (typeof decision.action_id !== "string" || !decision.action_id || typeof decision.receipt_id !== "string" ||
    !decision.receipt_id || typeof call.tool_call_id !== "string" || !call.tool_call_id) return { state: "rejected" };
  const deadline = Math.min(Date.now() + cfg.holdWaitMs, hookDeadline);
  while (!signal?.aborted && Date.now() < deadline) {
    const status = await post<Record<string, unknown>>("/v1/hold-status", {
      ...call,
      task_id: decision.task_id ?? "",
      runtime_task_id: decision.runtime_task_id ?? "",
      action_id: decision.action_id,
      decision_receipt_id: decision.receipt_id,
    }, signal, deadline - Date.now());
    if (signal?.aborted) return { state: "rejected" };
    if (!status || status.schema_version !== "hold-status/v1" || status.action_id !== decision.action_id ||
      status.decision_receipt_id !== decision.receipt_id || typeof status.expires_at !== "string" ||
      !["pending", "approved", "denied", "expired", "consumed"].includes(String(status.status))) return { state: "unavailable" };
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(status.expires_at)) return { state: "unavailable" };
    const expires = Date.parse(status.expires_at);
    if (!Number.isFinite(expires)) return { state: "unavailable" };
    if (Date.now() >= deadline || Date.now() >= expires) return { state: "rejected" };
    if (status.status === "approved" && status.reason_code === "hold_approved") return { state: "approved", expires };
    if (status.status !== "pending" || status.reason_code !== "hold_pending") return { state: "rejected" };
    await pause(Math.min(250, deadline - Date.now(), expires - Date.now()), signal);
  }
  return { state: "rejected" };
}

function retryToolCallId(decision: Decision, originalToolCallId: string): string {
  const digest = createHash("sha256")
    .update(`${decision.action_id}\u0000${decision.receipt_id}\u0000${originalToolCallId}`)
    .digest("hex");
  return `siq-retry-${digest}`;
}

async function reserveHoldExecution(
  decision: Decision,
  call: Record<string, unknown>,
  finalParams: Record<string, unknown>,
  deadline: number,
  signal?: AbortSignal,
): Promise<{
  retryToolCallId: string;
  reservationReceiptId: string;
  params: Record<string, unknown>;
} | null> {
  if (
    typeof decision.action_id !== "string" ||
    !decision.action_id ||
    typeof decision.receipt_id !== "string" ||
    !decision.receipt_id ||
    typeof call.tool_call_id !== "string" ||
    !call.tool_call_id ||
    deadline <= Date.now()
  ) {
    return null;
  }
  let params: Record<string, unknown>;
  try {
    const snapshot = JSON.parse(JSON.stringify(finalParams));
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return null;
    params = snapshot as Record<string, unknown>;
  } catch {
    return null;
  }
  const retry = retryToolCallId(decision, call.tool_call_id);
  if (retry === call.tool_call_id) return null;
  const reservation = await post<HoldExecutionReservation>(
    "/v1/hold-executions/reserve",
    {
      schema_version: "hold-execution-reserve/v1",
      platform: call.platform,
      session_id: call.session_id,
      agent_id: call.agent_id,
      task_id: decision.task_id ?? "",
      runtime_task_id: decision.runtime_task_id ?? "",
      tool: call.tool,
      original_tool_call_id: call.tool_call_id,
      retry_tool_call_id: retry,
      action_id: decision.action_id,
      decision_receipt_id: decision.receipt_id,
      params,
    },
    signal,
    deadline - Date.now(),
    201,
  );
  if (
    !reservation ||
    reservation.schema_version !== "hold-execution-status/v1" ||
    reservation.status !== "reserved" ||
    reservation.action_id !== decision.action_id ||
    reservation.decision_receipt_id !== decision.receipt_id ||
    typeof reservation.reservation_receipt_id !== "string" ||
    !reservation.reservation_receipt_id ||
    reservation.reason_code !== "hold_execution_reserved" ||
    typeof reservation.expires_at !== "string" ||
    !Number.isFinite(Date.parse(reservation.expires_at)) ||
    Date.parse(reservation.expires_at) <= Date.now() ||
    signal?.aborted
  ) {
    return null;
  }
  return {
    retryToolCallId: retry,
    reservationReceiptId: reservation.reservation_receipt_id,
    params,
  };
}

function failClosed(reason: string, tool = "", sessionId = "") {
  const mode = cfg.enforcementMode;
  const mustBlock = mode === "block" || managed() || cfg.configError === true || !localEndpoint();
  const outcome = mustBlock ? "deny" : "allow";
  appendPending({
    schema: "pending_decision/v1",
    recorded_at: new Date().toISOString(),
    platform: "openclaw",
    tool,
    session_id: sessionId,
    enforcement_mode: mode,
    outcome,
    reason: reason.startsWith("decision") ? reason : `decision service unavailable (${reason})`,
    signed: false,
  });
  if (mustBlock) {
    return { block: true, blockReason: `siq-agent-security: decision service unavailable (${reason}); blocked (fail-closed)` };
  }
  console.warn(`siq-agent-security: decision service unavailable (${reason}); allowing in ${mode} mode`);
  return undefined;
}

function appendPending(rec: Record<string, unknown>): void {
  try {
    const root = cfg.tokenPath ? join(cfg.tokenPath, managed() ? "../.." : "..") : stateDir();
    const dir = join(root, "pending");
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    appendFileSync(join(dir, "decisions.jsonl"), JSON.stringify(rec) + "\n", { mode: 0o600 });
  } catch {
    /* best-effort local pending log */
  }
}

type Correlation = {
  expires: number;
  action_id: string;
  decision_receipt_id: string;
  executable?: boolean;
  consumed?: boolean;
  execution?: {
    tool_call_id: string;
    decision_receipt_id: string;
    params: Record<string, unknown>;
  };
};
const correlations = new Map<string, Correlation>();
const correlationKey = (session: string, tool: string, call: string) => JSON.stringify([session, tool, call]);
function rememberDecision(session: string, tool: string, call: string, decision: Decision): boolean {
  if (!call || !decision.action_id || !decision.receipt_id) return !managed();
  const now = Date.now();
  for (const [key, value] of correlations) if (value.expires <= now) correlations.delete(key);
  const key = correlationKey(session, tool, call);
  if (correlations.has(key)) {
    correlations.set(key, { expires: now + 300_000, action_id: "", decision_receipt_id: "" });
    return false;
  }
  if (correlations.size >= 2048) return false;
  correlations.set(key, { expires: now + 300_000, action_id: decision.action_id, decision_receipt_id: decision.receipt_id,
    executable: decision.action === "allow" || (decision.action === "redact" && !!decision.params) });
  return true;
}
function decisionReference(session: string, tool: string, call: string): {
  action_id?: string;
  decision_receipt_id?: string;
  tool_call_id?: string;
  params?: Record<string, unknown>;
} {
  const value = correlations.get(correlationKey(session, tool, call));
  if (!value || !value.action_id || !value.executable || value.consumed || value.expires <= Date.now()) return {};
  value.consumed = true;
  return {
    action_id: value.action_id,
    decision_receipt_id: value.execution?.decision_receipt_id ?? value.decision_receipt_id,
    tool_call_id: value.execution?.tool_call_id,
    params: value.execution?.params,
  };
}

// Managed mode: every native session proves its runtime identity once per
// tool call; the daemon binds it to the signed intent (Hermes parity).
async function enrollRuntimeSession(session: string, signal?: AbortSignal, remainingMs?: number): Promise<boolean> {
  if (!managed()) return true;
  if (!RUNTIME_ID_RE.test(cfg.runtimeIdentityId ?? "") || !AGENT_ID_RE.test(cfg.agentId) ||
    typeof session !== "string" || !session || session.length > 256) return false;
  const result = await post<Record<string, unknown>>("/v1/runtime-sessions", {
    schema_version: "local-runtime-session-enroll/v1", session_id: session,
  }, signal, remainingMs);
  if (!result) return false;
  const expected = ["schema_version", "identity_id", "platform", "agent_id", "session_id",
    "binding_id", "intent_id", "expires_at"];
  const keys = Object.keys(result);
  if (keys.length !== expected.length || !keys.every((k) => expected.includes(k))) return false;
  return result.schema_version === "local-runtime-session-enrolled/v1" &&
    result.identity_id === cfg.runtimeIdentityId &&
    result.platform === "openclaw" &&
    result.agent_id === cfg.agentId &&
    result.session_id === session &&
    typeof result.binding_id === "string" && /^bind-[a-f0-9]{64}$/.test(result.binding_id) &&
    typeof result.intent_id === "string" && /^int-ri-[a-f0-9]{64}$/.test(result.intent_id) &&
    typeof result.expires_at === "string" && Date.parse(result.expires_at) > Date.now();
}

interface RawField { path: string; value: string; secret: boolean; }

// Flatten JSON-compatible host values into bounded JSON-pointer fields; the
// server applies its own secret filtering and raw-content policy.
function rawContentFields(tool: string, root: string, value: unknown): RawField[] | null {
  if (typeof tool !== "string" || !tool) return null;
  const fields: RawField[] = [{ path: "/tool/name", value: tool, secret: false }];
  const append = (path: string, current: unknown, depth: number): boolean => {
    if (depth > 32 || path.length > 256 || /[\x00-\x1f]/.test(path)) return false;
    if (current !== null && typeof current === "object" && !Array.isArray(current)) {
      const entries = Object.entries(current as Record<string, unknown>);
      if (entries.length === 0) fields.push({ path, value: "{}", secret: false });
      for (const [key, item] of entries) {
        if (!key) return false;
        const segment = key.replace(/~/g, "~0").replace(/\//g, "~1");
        if (!append(`${path}/${segment}`, item, depth + 1)) return false;
      }
      return fields.length <= 1024;
    }
    if (Array.isArray(current)) {
      if (current.length === 0) fields.push({ path, value: "[]", secret: false });
      for (let index = 0; index < current.length; index++) {
        if (!append(`${path}/${index}`, current[index], depth + 1)) return false;
      }
      return fields.length <= 1024;
    }
    if (typeof current === "number" && !Number.isFinite(current)) return false;
    // Host payloads (e.g. OpenClaw tool-result carriers) carry undefined
    // function-slot fields; they hold no content, so skip rather than abort.
    if (current === undefined || typeof current === "function" || typeof current === "symbol") return true;
    let encoded: string;
    try {
      const json = JSON.stringify(current);
      if (json === undefined) return false;
      encoded = json;
    } catch {
      return false;
    }
    if (!encoded || Buffer.byteLength(encoded, "utf8") > (1 << 20)) return false;
    fields.push({ path, value: encoded, secret: false });
    return fields.length <= 1024;
  };
  return append(root, value, 0) ? fields : null;
}

// Offer native raw content to the daemon; it owns the raw-content policy and
// does the capture. Best effort with a hard 250 ms budget, like Hermes.
async function captureNativeRawContent(
  kind: "parameters" | "output", session: string, tool: string, value: unknown,
): Promise<void> {
  if (!RUNTIME_ID_RE.test(cfg.runtimeIdentityId ?? "") || !AGENT_ID_RE.test(cfg.agentId) ||
    typeof session !== "string" || !session || session.length > 256) return;
  const fields = rawContentFields(tool, kind === "parameters" ? "/tool/arguments" : "/tool/result", value);
  if (!fields) return;
  await post("/v1/raw-task-content/native-captures", {
    schema_version: "local-raw-task-content-native-capture/v1",
    platform: "openclaw",
    agent_id: cfg.agentId,
    session_id: session,
    kind,
    fields,
  }, undefined, 250, 201);
}

// In managed mode the daemon binds the native session to the pinned instance
// agent (cfg.agentId); a host-supplied agent id would fail the session
// authorization and leak a forgeable agent identity into receipts.
function reportedAgentId(ctx?: { agentId?: string }): string {
  if (managed()) return cfg.agentId;
  return ctx?.agentId ?? cfg.agentId;
}

export default definePluginEntry({
  id: "siq-agent-security",
  name: "siq-agent-security",
  register(api) {
    api.on(
      "before_tool_call",
      async (event, ctx) => {
        const hookDeadline = Date.now() + 12000;
        const call = {
          platform: "openclaw",
          session_id: (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? (managed() ? "" : "openclaw-default"),
          agent_id: reportedAgentId(ctx as { agentId?: string } | undefined),
          tool: event.toolName,
          tool_call_id: event.toolCallId ?? "",
          params: event.params ?? {},
        };
        // A repeated pre-hook invalidates even an earlier allow if this attempt
        // later fails enrollment, is denied, or returns a malformed response.
        const prior = correlations.get(correlationKey(call.session_id, call.tool, call.tool_call_id));
        if (prior && prior.expires > Date.now()) {
          prior.action_id = "";
          prior.executable = false;
          return { block: true, blockReason: "siq-agent-security: duplicate tool call" };
        }
        if (!(await enrollRuntimeSession(call.session_id, ctx?.abortSignal, hookDeadline - Date.now()))) {
          return failClosed("instance session could not be verified", event.toolName, call.session_id);
        }
        const decision = await post<Decision>(
          "/v1/decide",
          {
            ...call,
            context: { host: "openclaw", tool_kind: (event as { toolKind?: string }).toolKind ?? "" },
          },
          ctx?.abortSignal,
          hookDeadline - Date.now(),
        );
        if (!decision) return failClosed("no response", event.toolName, (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default");
        if (typeof decision.reason !== "string" || typeof decision.receipt_id !== "string" || !decision.receipt_id ||
          (managed() && ["allow", "redact", "hold"].includes(decision.action) &&
            (typeof decision.action_id !== "string" || !decision.action_id || !call.tool_call_id))) {
          return failClosed("malformed decision reference", event.toolName, call.session_id);
        }
        if (["allow", "redact", "hold"].includes(decision.action) && !rememberDecision(
          (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default",
          event.toolName, event.toolCallId ?? "", decision,
        )) return failClosed("decision correlation conflict or capacity", event.toolName);
        switch (decision.action) {
          case "allow":
            await captureNativeRawContent("parameters", call.session_id, event.toolName, event.params ?? {});
            return undefined;
          case "deny":
            return { block: true, blockReason: `siq-agent-security denied: ${decision.reason} (receipt ${decision.receipt_id})` };
          case "redact":
            return decision.params ? { params: decision.params } : { block: true, blockReason: "siq-agent-security: redaction failed" };
          case "hold": {
            if ((ctx as { approvalExecutionRecheckVersion?: unknown } | undefined)?.approvalExecutionRecheckVersion !== 1) {
              return failClosed("native approval execution recheck unsupported", event.toolName, call.session_id);
            }
            const approval = await waitForLocalApproval(decision, call, hookDeadline, ctx?.abortSignal);
            if (approval.state === "unavailable") return failClosed("local approval status unavailable", event.toolName, call.session_id);
            if (approval.state !== "approved" || !approval.expires || ctx?.abortSignal?.aborted) {
              return { block: true, blockReason: `siq-agent-security: local approval required or expired (receipt ${decision.receipt_id})` };
            }
            return {
              requireApproval: {
                title: `siq-agent-security: approve ${event.toolName}?`,
                description: `${decision.reason} (receipt ${decision.receipt_id})`,
                severity: "warning",
                timeoutMs: Math.max(1, approval.expires - Date.now()),
                timeoutBehavior: "deny",
                beforeExecute: async (finalParams: Record<string, unknown>, signal?: AbortSignal) => {
                  const deadline = Date.now() + 1000;
                  const checked = await waitForLocalApproval(
                    decision, { ...call, params: finalParams }, deadline, signal,
                  );
                  const ref = correlations.get(correlationKey(call.session_id, call.tool, call.tool_call_id));
                  const approved = checked.state === "approved" && !signal?.aborted && deadline > Date.now() &&
                    !!ref && ref.action_id === decision.action_id && !ref.consumed && !ref.executable && ref.expires > Date.now();
                  if (!approved || !ref) {
                    if (ref) ref.executable = false;
                    return false;
                  }
                  const reservation = await reserveHoldExecution(decision, call, finalParams, deadline, signal);
                  const executable = !!reservation && !signal?.aborted;
                  ref.executable = executable;
                  ref.execution = executable
                    ? {
                        tool_call_id: reservation.retryToolCallId,
                        decision_receipt_id: reservation.reservationReceiptId,
                        params: reservation.params,
                      }
                    : undefined;
                  if (executable) {
                    await captureNativeRawContent("parameters", call.session_id, event.toolName, reservation.params);
                  }
                  if (signal?.aborted) {
                    ref.executable = false;
                    return false;
                  }
                  return executable;
                },
              },
            };
          }
          default:
            return failClosed("malformed decision", event.toolName, (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default");
        }
      },
      { priority: 10 },
    );

    api.on("after_tool_call", async (event, ctx) => {
      const session = (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default";
      const result = (event as { result?: unknown }).result;
      const text = typeof result === "string" ? result : JSON.stringify(result ?? "");
      const reference = decisionReference(session, event.toolName, event.toolCallId ?? "");
      const observedToolCallID = reference.tool_call_id ?? event.toolCallId ?? "";
      const observedParams = reference.params ?? event.params ?? {};
      await post("/v1/observe", {
        platform: "openclaw",
        session_id: session,
        agent_id: reportedAgentId(ctx as { agentId?: string } | undefined),
        tool: event.toolName,
        tool_call_id: observedToolCallID,
        params: observedParams,
        action_id: reference.action_id,
        decision_receipt_id: reference.decision_receipt_id,
        result: text.slice(0, 64 * 1024),
      });
      if (reference.action_id) {
        await captureNativeRawContent("output", session, event.toolName, result);
      }
    });
  },
});
