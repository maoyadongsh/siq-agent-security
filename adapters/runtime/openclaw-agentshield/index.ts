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
 *   hold   → { requireApproval: { title, description, severity, timeoutMs } }
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
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

type Mode = "audit_only" | "warn" | "block";

interface Config {
  endpoint: string;
  tokenPath: string;
  enforcementMode: Mode;
  timeoutMs: number;
  agentId: string;
}

interface Decision {
  action: "allow" | "deny" | "hold" | "redact";
  reason: string;
  receipt_id: string;
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
    agentId: env("SIQ_AGENT_SECURITY_AGENT_ID", "AGENTSHIELD_AGENT_ID") || "default",
  };
  const home = homedir();
  for (const name of ["siq-agent-security.json", "agentshield.json"]) {
    try {
      Object.assign(cfg, JSON.parse(readFileSync(join(home, ".openclaw", name), "utf8")));
      break;
    } catch {
      /* try next */
    }
  }
  const endpoint = env("SIQ_AGENT_SECURITY_ENDPOINT", "AGENTSHIELD_ENDPOINT");
  if (endpoint) cfg.endpoint = endpoint;
  const mode = env("SIQ_AGENT_SECURITY_MODE", "AGENTSHIELD_MODE");
  if (mode) cfg.enforcementMode = mode as Mode;
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

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T | null> {
  const tok = readToken();
  if (!tok) return null;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), cfg.timeoutMs);
  signal?.addEventListener("abort", () => ctrl.abort(), { once: true });
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
  }
}

function failClosed(reason: string) {
  if (cfg.enforcementMode === "block") {
    return { block: true, blockReason: `siq-agent-security: decision service unavailable (${reason}); blocked (fail-closed)` };
  }
  console.warn(`siq-agent-security: decision service unavailable (${reason}); allowing in ${cfg.enforcementMode} mode`);
  return undefined;
}

export default definePluginEntry({
  id: "siq-agent-security",
  name: "siq-agent-security",
  register(api) {
    api.on(
      "before_tool_call",
      async (event, ctx) => {
        const decision = await post<Decision>(
          "/v1/decide",
          {
            platform: "openclaw",
            session_id: (event as { sessionKey?: string }).sessionKey ?? ctx?.sessionKey ?? "openclaw-default",
            agent_id: (ctx as { agentId?: string } | undefined)?.agentId ?? cfg.agentId,
            tool: event.toolName,
            tool_call_id: event.toolCallId ?? "",
            params: event.params ?? {},
            context: { host: "openclaw", tool_kind: (event as { toolKind?: string }).toolKind ?? "" },
          },
          ctx?.abortSignal,
        );
        if (!decision) return failClosed("no response");
        switch (decision.action) {
          case "allow":
            return undefined;
          case "deny":
            return { block: true, blockReason: `siq-agent-security denied: ${decision.reason} (receipt ${decision.receipt_id})` };
          case "redact":
            return decision.params ? { params: decision.params } : { block: true, blockReason: "siq-agent-security: redaction failed" };
          case "hold":
            return {
              requireApproval: {
                title: `siq-agent-security: approve ${event.toolName}?`,
                description: `${decision.reason} (receipt ${decision.receipt_id})`,
                severity: "warning",
                timeoutMs: decision.hold?.timeout_ms ?? 60_000,
              },
            };
          default:
            return failClosed("malformed decision");
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
        params: {},
        result: text.slice(0, 64 * 1024),
      });
    });
  },
});
