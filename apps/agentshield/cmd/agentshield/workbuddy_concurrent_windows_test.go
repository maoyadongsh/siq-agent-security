package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/pending"
)

// A real loopback server stalls one decision while ten independent native calls
// contend for correlation. This reproduces scope-lock admission, not the
// historical J-02 incident (whose original scheduling is unknown).
func TestWorkBuddyManagedConcurrentIndependentCalls(t *testing.T) {
	testWorkBuddyConcurrentCalls(t, false, false)
}

func TestWorkBuddyManagedConcurrentProcesses(t *testing.T) {
	for _, sameTarget := range []bool{false, true} {
		t.Run(fmt.Sprintf("same_target_%t", sameTarget), func(t *testing.T) { testWorkBuddyConcurrentCalls(t, true, sameTarget) })
	}
}

func TestWorkBuddyManagedProcessHelper(t *testing.T) {
	if os.Getenv("SIQ_TEST_WORKBUDDY_PROCESS") != "1" {
		return
	}
	if err := runWorkBuddyManagedHookWithBudget(os.Getenv("SIQ_TEST_WORKBUDDY_CONFIG"), os.Getenv("SIQ_TEST_WORKBUDDY_STATE"), os.Stdin, os.Stdout, 20*time.Second); err != nil {
		os.Exit(2)
	}
	os.Exit(0)
}

func testWorkBuddyConcurrentCalls(t *testing.T, processes, sameTarget bool) {
	var cfg adapters.WorkBuddyManagedConfig
	var decided atomic.Int32
	var path string
	cfg, path = managedWorkBuddyFixture(t, func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
			return
		}
		if r.URL.Path == "/v1/runtime-sessions" {
			_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "local-runtime-session-enrolled/v2", "identity_id": cfg.RuntimeIdentityID, "platform": "workbuddy", "agent_id": cfg.AgentID, "session_id": body["session_id"], "binding_id": "ib-fixture", "intent_id": "int-fixture", "expires_at": time.Now().Add(time.Hour).UTC().Format(time.RFC3339)})
			return
		}
		if r.URL.Path != "/v1/decide" {
			t.Errorf("unexpected endpoint %s", r.URL.Path)
			return
		}
		decided.Add(1)
		time.Sleep(50 * time.Millisecond)
		_ = json.NewEncoder(w).Encode(map[string]any{"action": "allow", "reason": "fixture", "receipt_id": fmt.Sprint("rcp-", body["tool_call_id"]), "action_id": fmt.Sprint("act-", body["tool_call_id"]), "authority_status": "valid", "effective_action": "allow"})
	})
	var wg sync.WaitGroup
	start := make(chan struct{})
	outputs := make([]adapters.WorkBuddyOutput, 10)
	errors := make([]error, len(outputs))
	for i := range outputs {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			call := fmt.Sprintf("independent-call-%d", i)
			target := i
			if sameTarget {
				target = 0
			}
			raw, _ := json.Marshal(map[string]any{"hook_event_name": "PreToolUse", "session_id": "same-native-session", "tool_use_id": call, "call_id": call, "tool_name": "Glob", "tool_input": map[string]any{"path": fmt.Sprintf("C:\\synthetic\\target-%d", target), "pattern": "*.txt"}})
			if !processes {
				outputs[i] = runManagedWorkBuddy(t, cfg, path, string(raw))
				return
			}
			ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
			defer cancel()
			command := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestWorkBuddyManagedProcessHelper$")
			command.Env = append(os.Environ(), "SIQ_TEST_WORKBUDDY_PROCESS=1", "SIQ_TEST_WORKBUDDY_CONFIG="+path, "SIQ_TEST_WORKBUDDY_STATE="+cfg.StateDir)
			command.Stdin = bytes.NewReader(raw)
			response, err := command.Output()
			if err == nil {
				err = json.Unmarshal(response, &outputs[i])
			}
			errors[i] = err
		}(i)
	}
	close(start)
	wg.Wait()
	defer func() {
		if t.Failed() {
			raw, _ := os.ReadFile(filepath.Join(cfg.StateDir, "pending", "decisions.jsonl"))
			for _, line := range bytes.Split(bytes.TrimSpace(raw), []byte{'\n'}) {
				var rec pending.Record
				if json.Unmarshal(line, &rec) == nil {
					t.Logf("local refusal call=%s stage=%s code=%s", rec.NativeCallID, rec.Stage, rec.ReasonCode)
				}
			}
		}
	}()
	blocked := 0
	for i, out := range outputs {
		if errors[i] != nil {
			t.Errorf("process %d failed: %v", i, errors[i])
			continue
		}
		if sameTarget && out.HookSpecificOutput.HookEventName == "PreToolUse" && out.HookSpecificOutput.PermissionDecision == "deny" && strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, "execution uncertain") {
			blocked++
			continue
		}
		if out.HookSpecificOutput.HookEventName != "PreToolUse" || out.HookSpecificOutput.PermissionDecision != "" {
			t.Errorf("independent call %d blocked: %s", i, out.HookSpecificOutput.PermissionDecisionReason)
		}
	}
	if sameTarget {
		// A new native call with identical effect can be a host retry after
		// unknown execution. No Post arrived: preserve this refusal, never
		// relax it merely to make all ten same-effect calls execute.
		if decided.Load() != 1 || blocked != 9 {
			t.Fatalf("same-effect unknown was replayed: decided=%d blocked=%d", decided.Load(), blocked)
		}
		raw, err := os.ReadFile(filepath.Join(cfg.StateDir, "pending", "decisions.jsonl"))
		if err != nil {
			t.Fatal(err)
		}
		lines := bytes.Split(bytes.TrimSpace(raw), []byte{'\n'})
		if len(lines) != 9 {
			t.Fatalf("lost concurrent local failures: %d", len(lines))
		}
		seen := map[string]bool{}
		for _, line := range lines {
			var rec pending.Record
			if json.Unmarshal(line, &rec) != nil || pending.ValidateLocalRecord(rec) != nil || rec.Stage != "correlation" || seen[rec.ToolCallID] {
				t.Fatal("local failures interleaved or lost call identity")
			}
			seen[rec.ToolCallID] = true
		}
	} else if decided.Load() != 10 {
		t.Fatalf("only %d/10 independent calls reached decision", decided.Load())
	}
}
