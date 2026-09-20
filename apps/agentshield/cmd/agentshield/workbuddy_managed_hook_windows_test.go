package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

const managedWorkBuddyInput = `{"hook_event_name":"PreToolUse","session_id":"host-session","tool_use_id":"host-call","call_id":"host-call","tool_name":"Read","tool_input":{"file_path":"C:\\fixture\\input.txt"}}`

func managedWorkBuddyFixture(t *testing.T, handler http.HandlerFunc) (adapters.WorkBuddyManagedConfig, string) {
	t.Helper()
	root := t.TempDir()
	dir := filepath.Join(root, "state")
	home := filepath.Join(root, "home")
	profile := filepath.Join(home, ".workbuddy")
	if _, err := state.Open(dir); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{profile, filepath.Join(dir, "runtime-identity-secrets")} {
		if err := statefs.MkdirAllPrivate(p); err != nil {
			t.Fatal(err)
		}
	}
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	instance := hermeshome.Identifier(profile)
	cfg := adapters.WorkBuddyManagedConfig{SchemaVersion: "workbuddy-managed-hook/v1", RuntimeIdentityID: "ri-" + strings.Repeat("c", 32), InstanceID: instance, AgentID: "hri-" + strings.TrimPrefix(instance, "hi-"), Endpoint: server.URL, EnforcementMode: "block", StateDir: dir}
	cfg.CredentialPath = filepath.Join(dir, "runtime-identity-secrets", cfg.RuntimeIdentityID+".token")
	write := func(path string, raw []byte) {
		t.Helper()
		f, err := statefs.CreatePrivate(path)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = f.Write(raw); err != nil {
			t.Fatal(err)
		}
		if err = f.Close(); err != nil {
			t.Fatal(err)
		}
	}
	path := filepath.Join(profile, "siq-agent-security.json")
	raw, _ := json.Marshal(cfg)
	write(path, raw)
	write(cfg.CredentialPath, []byte(strings.Repeat("scoped-fixture-", 4)))
	// A working global token must never repair missing managed credentials.
	write(filepath.Join(dir, "token"), []byte(strings.Repeat("global-fixture-", 4)))
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	t.Setenv("USERPROFILE", home)
	t.Setenv("HOME", home)
	t.Setenv("WORKBUDDY_CONFIG_DIR", profile)
	return cfg, path
}

func runManagedWorkBuddy(t *testing.T, cfg adapters.WorkBuddyManagedConfig, path, input string) adapters.WorkBuddyOutput {
	t.Helper()
	var out bytes.Buffer
	if err := runWorkBuddyManagedHook(path, cfg.StateDir, strings.NewReader(input), &out); err != nil {
		t.Fatal("unsafe nonblocking CLI error", err)
	}
	var decoded adapters.WorkBuddyOutput
	if err := json.Unmarshal(out.Bytes(), &decoded); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "scoped-fixture") || strings.Contains(out.String(), "global-fixture") || strings.Contains(out.String(), cfg.StateDir) {
		t.Fatal("hook leaked private configuration")
	}
	return decoded
}

func TestWorkBuddyManagedHTTPEnrolledDecideObserve(t *testing.T) {
	var cfg adapters.WorkBuddyManagedConfig
	paths := []string{}
	session, _ := runtimeidentity.WorkBuddySessionID("host-session")
	call, _ := runtimeidentity.WorkBuddyCallID("host-session", "host-call")
	handler := func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.Path)
		if r.Header.Get("Authorization") != "Bearer "+strings.Repeat("scoped-fixture-", 4) {
			t.Error("wrong credential")
		}
		var body map[string]any
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			t.Error("bad request")
		}
		if body["session_id"] != session {
			t.Error("wrong session")
		}
		if r.URL.Path == "/v1/runtime-sessions" {
			time.Sleep(21 * time.Second) // Installed Skill validation can exceed the former shared twenty-second budget.
			_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "local-runtime-session-enrolled/v2", "identity_id": cfg.RuntimeIdentityID, "platform": "workbuddy", "agent_id": cfg.AgentID, "session_id": session, "binding_id": "ib-fixture", "intent_id": "int-fixture", "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339)})
			return
		}
		if body["agent_id"] != cfg.AgentID || body["platform"] != "workbuddy" || body["tool_call_id"] != call {
			t.Error("wrong call identity")
		}
		if r.URL.Path == "/v1/decide" {
			_ = json.NewEncoder(w).Encode(map[string]any{"action": "allow", "reason": "fixture", "receipt_id": "rcp-fixture", "action_id": "act-fixture", "authority_status": "valid", "effective_action": "allow"})
			return
		}
		if r.URL.Path == "/v1/observe" {
			_ = json.NewEncoder(w).Encode(map[string]any{"receipt_id": "rcp-fixture-obs", "action_id": "act-fixture", "taint_labels": []string{}})
			return
		}
		t.Error("unexpected management request")
	}
	var path string
	cfg, path = managedWorkBuddyFixture(t, handler)
	// Proxy settings cannot redirect the dedicated bearer away from loopback.
	t.Setenv("HTTP_PROXY", "http://127.0.0.1:1")
	t.Setenv("ALL_PROXY", "http://127.0.0.1:1")
	pre := runManagedWorkBuddy(t, cfg, path, managedWorkBuddyInput)
	if pre.HookSpecificOutput.PermissionDecision != "" {
		t.Fatalf("allow overrode host permission: %+v", pre)
	}
	post := strings.Replace(managedWorkBuddyInput, "PreToolUse", "PostToolUse", 1)
	post = strings.TrimSuffix(post, "}") + `,"tool_response":"read-ok"}`
	result := runManagedWorkBuddy(t, cfg, path, post)
	if result.HookSpecificOutput.HookEventName != "PostToolUse" || result.HookSpecificOutput.PermissionDecisionReason != "" || strings.Join(paths, ",") != "/v1/runtime-sessions,/v1/decide,/v1/observe" {
		t.Fatalf("chain mismatch: %+v %v", result, paths)
	}
}

func TestWorkBuddyManagedBadConfigurationNeverUsesGlobalToken(t *testing.T) {
	for _, kind := range []string{"missing-config", "broken-config", "missing-credential", "shared-token", "wrong-instance", "redirect", "wrong-enroll-session", "duplicate-enroll", "legacy-enroll", "no-flag-residual"} {
		t.Run(kind, func(t *testing.T) {
			requests := 0
			redirected := 0
			var cfg adapters.WorkBuddyManagedConfig
			destination := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { redirected++; w.WriteHeader(200) }))
			defer destination.Close()
			cfg, path := managedWorkBuddyFixture(t, func(w http.ResponseWriter, r *http.Request) {
				requests++
				if kind == "redirect" {
					http.Redirect(w, r, destination.URL, http.StatusTemporaryRedirect)
					return
				}
				session, _ := runtimeidentity.WorkBuddySessionID("host-session")
				if kind == "wrong-enroll-session" {
					session = "workbuddy-session/v1:" + strings.Repeat("f", 64)
				}
				version := "local-runtime-session-enrolled/v2"
				if kind == "legacy-enroll" {
					version = "local-runtime-session-enrolled/v1"
				}
				body := map[string]any{"schema_version": version, "identity_id": cfg.RuntimeIdentityID, "platform": "workbuddy", "agent_id": cfg.AgentID, "session_id": session, "binding_id": "ib-fixture", "intent_id": "int-fixture", "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339)}
				raw, _ := json.Marshal(body)
				if kind == "duplicate-enroll" {
					raw = []byte(strings.Replace(string(raw), `"session_id":`, `"session_id":"forged","session_id":`, 1))
				}
				_, _ = w.Write(raw)
			})
			switch kind {
			case "missing-config":
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
			case "broken-config", "no-flag-residual":
				if err := os.WriteFile(path, []byte(`{"enforcement_mode":"audit_only",broken`), 0600); err != nil {
					t.Fatal(err)
				}
			case "missing-credential":
				if err := os.Remove(cfg.CredentialPath); err != nil {
					t.Fatal(err)
				}
			case "shared-token", "wrong-instance":
				altered := cfg
				if kind == "shared-token" {
					altered.CredentialPath = filepath.Join(cfg.StateDir, "token")
				} else {
					altered.InstanceID = "hi-" + strings.Repeat("d", 32)
				}
				raw, _ := json.Marshal(altered)
				if err := os.WriteFile(path, raw, 0600); err != nil {
					t.Fatal(err)
				}
			}
			var got adapters.WorkBuddyOutput
			if kind == "no-flag-residual" {
				var out bytes.Buffer
				if err := runWorkBuddySelectedHook("", false, strings.NewReader(managedWorkBuddyInput), &out); err != nil {
					t.Fatal(err)
				}
				_ = json.Unmarshal(out.Bytes(), &got)
			} else {
				got = runManagedWorkBuddy(t, cfg, path, managedWorkBuddyInput)
			}
			if got.HookSpecificOutput.PermissionDecision != "deny" || redirected != 0 || requests > 1 {
				t.Fatalf("managed failure did not stop chain: %+v req=%d redirect=%d", got, requests, redirected)
			}
			if (kind == "missing-config" || kind == "broken-config" || kind == "missing-credential" || kind == "shared-token" || kind == "wrong-instance" || kind == "no-flag-residual") && requests != 0 {
				t.Fatal("bad local config reached HTTP")
			}
		})
	}
}

func TestWorkBuddyManagedHTTPBudgetDoesNotResetAfterEnroll(t *testing.T) {
	var cfg adapters.WorkBuddyManagedConfig
	var path string
	cfg, path = managedWorkBuddyFixture(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/runtime-sessions" {
			time.Sleep(10 * time.Second)
			session, _ := runtimeidentity.WorkBuddySessionID("host-session")
			_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "local-runtime-session-enrolled/v2", "identity_id": cfg.RuntimeIdentityID, "platform": "workbuddy", "agent_id": cfg.AgentID, "session_id": session, "binding_id": "ib-fixture", "intent_id": "int-fixture", "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339)})
			return
		}
		select {
		case <-r.Context().Done():
		case <-time.After(15 * time.Second):
			_, _ = fmt.Fprint(w, `{"action":"allow"}`)
		}
	})
	start := time.Now()
	var out bytes.Buffer
	if err := runWorkBuddyManagedHookWithBudget(path, cfg.StateDir, strings.NewReader(managedWorkBuddyInput), &out, 20*time.Second); err != nil {
		t.Fatal(err)
	}
	var got adapters.WorkBuddyOutput
	if err := json.Unmarshal(out.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	elapsed := time.Since(start)
	if got.HookSpecificOutput.PermissionDecision != "deny" || elapsed > 23*time.Second || elapsed < 19*time.Second {
		t.Fatalf("budget changed: %v %+v", elapsed, got)
	}
}

func TestWorkBuddyEnrollmentDeadlineStage(t *testing.T) {
	for _, before := range []bool{true, false} {
		t.Run(fmt.Sprint(before), func(t *testing.T) {
			reached := make(chan struct{}, 1)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				reached <- struct{}{}
				select {
				case <-r.Context().Done():
				case <-time.After(time.Second):
				}
			}))
			defer server.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()
			if before {
				cancel()
			}
			client := &workBuddyManagedClient{config: adapters.WorkBuddyManagedConfig{Endpoint: server.URL}, token: "private-fixture", client: server.Client(), ctx: ctx}
			err := client.Enroll("fixture")
			var stage *adapters.WorkBuddyEnrollmentDeadline
			if !errors.As(err, &stage) || stage.BeforeRequest != before || strings.Contains(err.Error(), "private") {
				t.Fatalf("unexpected error: %v", err)
			}
			if before {
				select {
				case <-reached:
					t.Fatal("expired request reached server")
				default:
				}
			} else {
				select {
				case <-reached:
				default:
					t.Fatal("no request reached server")
				}
			}
		})
	}
}
