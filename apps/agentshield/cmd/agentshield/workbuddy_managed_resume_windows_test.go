package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

type workBuddyResumeFixture struct {
	t            *testing.T
	mu           sync.Mutex
	cfg          adapters.WorkBuddyManagedConfig
	path         string
	status       string
	fault        string
	requests     map[string]int
	originalCall string
	reservedCall string
}

func newWorkBuddyResumeFixture(t *testing.T) *workBuddyResumeFixture {
	t.Helper()
	f := &workBuddyResumeFixture{t: t, status: "pending", requests: map[string]int{}}
	f.originalCall, _ = runtimeidentity.WorkBuddyCallID("host-session", "host-call")
	f.cfg, f.path = managedWorkBuddyFixture(t, f.serve)
	return f
}

func (f *workBuddyResumeFixture) serve(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.requests[r.URL.Path]++
	var body map[string]any
	if json.NewDecoder(r.Body).Decode(&body) != nil {
		f.t.Error("invalid request JSON")
		w.WriteHeader(400)
		return
	}
	session, _ := runtimeidentity.WorkBuddySessionID("host-session")
	expires := time.Now().Add(time.Minute).UTC().Format(time.RFC3339Nano)
	if r.URL.Path == "/v1/runtime-sessions" {
		_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "local-runtime-session-enrolled/v2", "identity_id": f.cfg.RuntimeIdentityID, "platform": "workbuddy", "agent_id": f.cfg.AgentID, "session_id": body["session_id"], "binding_id": "ib-fixture", "intent_id": "int-fixture", "expires_at": expires})
		return
	}
	if body["platform"] != "workbuddy" || body["agent_id"] != f.cfg.AgentID || body["session_id"] != session {
		f.t.Error("wrong authority tuple")
	}
	switch r.URL.Path {
	case "/v1/decide":
		if f.requests[r.URL.Path] > 1 {
			f.t.Error("unexpected fallback decide")
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"action": "hold", "reason": "fixture approval", "receipt_id": "rcp-hold", "action_id": "act-hold", "authority_status": "valid", "effective_action": "hold", "task_id": "trusted-intent-task", "runtime_task_id": "trusted-intent-task", "hold": map[string]any{"channel": "local", "timeout_ms": 60000, "resolved_by_receipt_id": nil}})
	case "/v1/hold-status":
		if body["tool_call_id"] != f.originalCall || body["action_id"] != "act-hold" || body["decision_receipt_id"] != "rcp-hold" || body["task_id"] != "trusted-intent-task" || body["runtime_task_id"] != "trusted-intent-task" {
			f.t.Error("hold lost original signed references")
		}
		if f.fault == "offline" {
			w.WriteHeader(503)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "hold-status/v1", "status": f.status, "action_id": "act-hold", "decision_receipt_id": "rcp-hold", "expires_at": expires, "reason_code": "hold_" + f.status})
	case "/v1/hold-executions/reserve":
		if body["original_tool_call_id"] != f.originalCall || body["retry_tool_call_id"] == f.originalCall || body["action_id"] != "act-hold" || body["decision_receipt_id"] != "rcp-hold" || body["task_id"] != "trusted-intent-task" {
			f.t.Error("reserve lost original authority")
		}
		f.reservedCall, _ = body["retry_tool_call_id"].(string)
		if f.fault == "lost-reserve" {
			w.WriteHeader(503)
			return
		}
		if f.fault == "revoked" {
			w.WriteHeader(401)
			return
		}
		w.WriteHeader(201)
		if f.fault == "malformed-reserve" {
			_, _ = fmt.Fprint(w, `{"status":"reserved"}`)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "hold-execution-status/v1", "status": "reserved", "action_id": "act-hold", "decision_receipt_id": "rcp-hold", "reservation_receipt_id": "rcp-hold-exec", "expires_at": expires, "reason_code": "hold_execution_reserved"})
	case "/v1/observe":
		if body["tool_call_id"] != f.reservedCall || body["action_id"] != "act-hold" || body["decision_receipt_id"] != "rcp-hold-exec" || body["task_id"] != "trusted-intent-task" {
			f.t.Error("post lost reserved execution reference")
		}
		if f.fault == "lost-post" {
			w.WriteHeader(503)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"receipt_id": "rcp-observed", "action_id": "act-hold", "taint_labels": []string{}})
	default:
		f.t.Error("unexpected route")
		w.WriteHeader(404)
	}
}

func (f *workBuddyResumeFixture) run(call string, post bool) adapters.CodeBuddyOutput {
	f.t.Helper()
	input := strings.ReplaceAll(managedWorkBuddyInput, "host-call", call)
	if post {
		input = strings.Replace(input, "PreToolUse", "PostToolUse", 1)
		input = strings.TrimSuffix(input, "}") + `,"tool_response":"fixture-result"}`
	}
	return runManagedWorkBuddy(f.t, f.cfg, f.path, input)
}

func (f *workBuddyResumeFixture) set(status, fault string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.status = status
	f.fault = fault
}
func (f *workBuddyResumeFixture) count(path string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.requests[path]
}

func TestWorkBuddyManagedResumeAcrossInvocations(t *testing.T) {
	f := newWorkBuddyResumeFixture(t)
	t.Log("initial hold")
	if out := f.run("host-call", false); out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("initial hold did not deny", out)
	}
	if out := f.run("pending-call", false); out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("pending approval allowed")
	}
	f.set("approved", "")
	t.Log("independent hook invocation consumes approved hold")
	if out := f.run("approved-call", false); out.HookSpecificOutput.PermissionDecision != "" {
		t.Fatal("approved retry blocked", out)
	}
	if out := f.run("approved-call", false); out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("duplicate pre allowed")
	}
	changed := strings.ReplaceAll(managedWorkBuddyInput, "host-call", "approved-call")
	changed = strings.Replace(changed, "input.txt", "changed.txt", 1)
	if out := runManagedWorkBuddy(t, f.cfg, f.path, changed); out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("same call with changed params replayed")
	}
	t.Log("post binds reservation receipt")
	if out := f.run("approved-call", true); out.HookSpecificOutput.PermissionDecisionReason != "" {
		t.Fatal("post correlation failed", out)
	}
	if out := f.run("approved-call", true); out.HookSpecificOutput.PermissionDecisionReason == "" {
		t.Fatal("duplicate post reported success")
	}
	if f.count("/v1/decide") != 1 || f.count("/v1/hold-executions/reserve") != 1 || f.count("/v1/observe") != 1 {
		t.Fatal("unexpected extra effect requests", f.requests)
	}
}

func TestWorkBuddyManagedResumeFailsClosed(t *testing.T) {
	for _, fault := range []string{"denied", "expired", "offline", "lost-reserve", "malformed-reserve", "revoked", "lost-post"} {
		t.Run(fault, func(t *testing.T) {
			f := newWorkBuddyResumeFixture(t)
			if out := f.run("host-call", false); out.HookSpecificOutput.PermissionDecision != "deny" {
				t.Fatal("initial hold allowed")
			}
			status := "approved"
			if fault == "denied" || fault == "expired" {
				status = fault
			}
			f.set(status, fault)
			out := f.run("retry-call", false)
			if fault == "lost-post" {
				if out.HookSpecificOutput.PermissionDecision != "" {
					t.Fatal("reservation failed", out)
				}
				if out = f.run("retry-call", true); out.HookSpecificOutput.PermissionDecisionReason == "" {
					t.Fatal("lost observation reported success")
				}
			} else if out.HookSpecificOutput.PermissionDecision != "deny" {
				t.Fatal("failure allowed", out)
			}
			if fault == "lost-reserve" || fault == "malformed-reserve" || fault == "revoked" || fault == "lost-post" {
				if out = f.run("another-call", false); out.HookSpecificOutput.PermissionDecision != "deny" || !strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, "uncertain") {
					t.Fatal("uncertain reservation replayed or hidden", out)
				}
			}
			if f.count("/v1/decide") != 1 || f.count("/v1/hold-executions/reserve") > 1 {
				t.Fatal("failed association fell back", f.requests)
			}
		})
	}
}

func TestWorkBuddyManagedMissingPreNeverFallsBack(t *testing.T) {
	var cfg adapters.WorkBuddyManagedConfig
	decides := 0
	cfg, path := managedWorkBuddyFixture(t, func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if r.URL.Path == "/v1/runtime-sessions" {
			_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "local-runtime-session-enrolled/v2", "identity_id": cfg.RuntimeIdentityID, "platform": "workbuddy", "agent_id": cfg.AgentID, "session_id": body["session_id"], "binding_id": "ib-fixture", "intent_id": "int-fixture", "expires_at": time.Now().Add(time.Minute).UTC().Format(time.RFC3339Nano)})
			return
		}
		if r.URL.Path != "/v1/decide" {
			t.Error("unexpected request", r.URL.Path)
			w.WriteHeader(400)
			return
		}
		decides++
		_ = json.NewEncoder(w).Encode(map[string]any{"action": "allow", "reason": "fixture", "receipt_id": "rcp-allow", "action_id": "act-allow", "authority_status": "valid", "effective_action": "allow"})
	})
	if out := runManagedWorkBuddy(t, cfg, path, managedWorkBuddyInput); out.HookSpecificOutput.PermissionDecision != "" {
		t.Fatal("initial allow failed", out)
	}
	files, err := filepath.Glob(filepath.Join(cfg.StateDir, "workbuddy-hooks", "*", "pre-*.json"))
	if err != nil || len(files) != 1 {
		t.Fatalf("expected own exact pre fixture: %v %v", files, err)
	}
	if err = os.Remove(files[0]); err != nil {
		t.Fatal(err)
	}
	input := strings.ReplaceAll(managedWorkBuddyInput, "host-call", "later-call")
	if out := runManagedWorkBuddy(t, cfg, path, input); out.HookSpecificOutput.PermissionDecision != "deny" || !strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, "uncertain") {
		t.Fatal("missing pre did not preserve uncertainty", out)
	}
	if decides != 1 {
		t.Fatalf("orphan allow reached a fresh decide %d times", decides)
	}
}
