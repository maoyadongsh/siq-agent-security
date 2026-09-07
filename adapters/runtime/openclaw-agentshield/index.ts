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
 *   hold   → wait for local approval, then require native platform approval
 *   redact → { params }  (host-owned params rewritten with secrets removed)
 *
 * Fail-closed table (§3.8.4): in `block` mode an unreachable / timed-out / 401 /
 * malformed service blocks the call; in `audit_only` / `warn` it allows and logs.
 * OpenClaw's own 15 s policy-hook timeout fails closed as the outer guard.
 *
 * Config: ~/.openclaw/siq-agent-security.json (legacy agentshield.json still read)
 *   { "endpoint": "http://127.0.0.1:47611", "tokenPath": "<state>/token",
 *     "enforcementMode": "block", "timeoutMs": 5000, "agentId": "default" }
 */
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
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
}

interface Decision {
  action: "allow" | "deny" | "hold" | "redact";
  reason: string;
  receipt_id: string;
  action_id?: string;
  params?: Record<string, unknown>;
  hold?: { channel: string; timeout_ms: number };
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
      Object.assign(cfg, JSON.parse(readFileSync(join(configDir, name), "utf8")));
      break;
    } catch {
      /* try next */
    }
  }
  const endpoint = env("SIQ_AGENT_SECURITY_ENDPOINT", "AGENTSHIELD_ENDPOINT");
  if (endpoint) cfg.endpoint = endpoint;
  const mode = env("SIQ_AGENT_SECURITY_MODE", "AGENTSHIELD_MODE");
  if (mode) cfg.enforcementMode = mode as Mode;
  if (!Number.isInteger(cfg.holdWaitMs) || cfg.holdWaitMs < 100 || cfg.holdWaitMs > 10000) cfg.holdWaitMs = 10000;
  return cfg;
}

const cfg = loadConfig();
let token: string | null = null;

function readToken(): string | null {
  if (token === null) {
    try {
      token = readFileSync(cfg.tokenPath, "ascii").trim();
    } catch {
      token = "";
    }
  }
  return token || null;
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal, remainingMs?: number): Promise<T | null> {
  if (signal?.aborted) return null;
  const tok = readToken();
  if (!tok) return null;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), Math.min(cfg.timeoutMs, remainingMs ?? cfg.timeoutMs));
  const abort = () => ctrl.abort();
  signal?.addEventListener("abort", abort, { once: true });
  try {
    const res = await fetch(cfg.endpoint.replace(/\/$/, "") + path, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${tok}` },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (res.status !== 200) return null;
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
      ...call, action_id: decision.action_id, decision_receipt_id: decision.receipt_id,
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

function failClosed(reason: string, tool = "", sessionId = "") {
  const mode = cfg.enforcementMode;
  const outcome = mode === "block" ? "deny" : "allow";
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
  if (mode === "block") {
    return { block: true, blockReason: `siq-agent-security: decision service unavailable (${reason}); blocked (fail-closed)` };
  }
  console.warn(`siq-agent-security: decision service unavailable (${reason}); allowing in ${mode} mode`);
  return undefined;
}

function appendPending(rec: Record<string, unknown>): void {
  try {
    const root = cfg.tokenPath ? join(cfg.tokenPath, "..") : stateDir();
    const dir = join(root, "pending");
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    appendFileSync(join(dir, "decisions.jsonl"), JSON.stringify(rec) + "\n", { mode: 0o600 });
  } catch {
    /* best-effort local pending log */
  }
}

type Correlation = { expires: number; action_id: string; decision_receipt_id: string };
const correlations = new Map<string, Correlation>();
const correlationKey = (session: string, tool: string, call: string) => JSON.stringify([session, tool, call]);
function rememberDecision(session: string, tool: string, call: string, decision: Decision): boolean {
  if (!call || !decision.action_id) return true;
  const now = Date.now();
  for (const [key, value] of correlations) if (value.expires <= now) correlations.delete(key);
  const key = correlationKey(session, tool, call);
  if (correlations.has(key)) {
    correlations.set(key, { expires: now + 300_000, action_id: "", decision_receipt_id: "" });
    return false;
  }
  if (correlations.size >= 2048) return false;
  correlations.set(key, { expires: now + 300_000, action_id: decision.action_id, decision_receipt_id: decision.receipt_id });
  return true;
}
function decisionReference(session: string, tool: string, call: string): Record<string, string> {
  const value = correlations.get(correlationKey(session, tool, call));
  return value && value.action_id && value.expires > Date.now()
    ? { action_id: value.action_id, decision_receipt_id: value.decision_receipt_id } : {};
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
          session_id: (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default",
          agent_id: (ctx as { agentId?: string } | undefined)?.agentId ?? cfg.agentId,
          tool: event.toolName,
          tool_call_id: event.toolCallId ?? "",
          params: event.params ?? {},
        };
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
        if (["allow", "redact", "hold"].includes(decision.action) && !rememberDecision(
          (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default",
          event.toolName, event.toolCallId ?? "", decision,
        )) return failClosed("decision correlation conflict or capacity", event.toolName);
        switch (decision.action) {
          case "allow":
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
                  const checked = await waitForLocalApproval(
                    decision, { ...call, params: finalParams }, Date.now() + 1000, signal,
                  );
                  return checked.state === "approved" && !signal?.aborted;
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
      const result = (event as { result?: unknown }).result;
      const text = typeof result === "string" ? result : JSON.stringify(result ?? "");
      await post("/v1/observe", {
        platform: "openclaw",
        session_id: (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default",
        agent_id: (ctx as { agentId?: string } | undefined)?.agentId ?? cfg.agentId,
        tool: event.toolName,
        tool_call_id: event.toolCallId ?? "",
        params: event.params ?? {},
        ...decisionReference(
          (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default",
          event.toolName, event.toolCallId ?? "",
        ),
        result: text.slice(0, 64 * 1024),
      });
    });
  },
});
