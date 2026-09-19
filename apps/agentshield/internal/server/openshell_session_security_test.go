package server

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func cloneExecBody(t *testing.T, body map[string]any) map[string]any {
	t.Helper()
	b, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err = json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestOpenShellPolicyOperationCannotUseOtherApproval(t *testing.T) {
	s, gw := newSessionExecServer(t)
	d := sessionExecApproveHold(t, s)
	cases := map[string]func(map[string]any){
		"unrelated_command": func(b map[string]any) { b["params"] = map[string]any{"command": "printf fixture"} },
		"target":            func(b map[string]any) { b["target"] = "other" },
		"binary":            func(b map[string]any) { b["binary_paths"] = []string{"/bin/sh"} },
		"empty_binary":      func(b map[string]any) { b["binary_paths"] = []string{} },
		"revision":          func(b map[string]any) { b["expected_revision"] = "2" },
		"endpoints":         func(b map[string]any) { b["endpoints"] = []string{"other.test:443"} },
		"params_and_outer": func(b map[string]any) {
			b["binary_paths"] = []string{"/bin/sh"}
			b["params"].(map[string]any)["openshell_policy"].(map[string]any)["binary_paths"] = []string{"/bin/sh"}
		},
		"grant_digest": func(b map[string]any) {
			b["params"].(map[string]any)["openshell_policy"].(map[string]any)["grant_digest"] = "changed"
		},
		"gateway": func(b map[string]any) {
			b["params"].(map[string]any)["openshell_policy"].(map[string]any)["endpoint_fingerprint"] = "changed"
		},
	}
	for name, change := range cases {
		t.Run(name, func(t *testing.T) {
			b := cloneExecBody(t, sessionExecBody(d))
			change(b)
			code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions", token, b)
			if code != 400 && code != 403 {
				t.Fatalf("tampered operation accepted: %d", code)
			}
			if gw.setCalls != 0 {
				t.Fatal("rejected request changed gateway")
			}
			if sessionExecHoldStatus(t, s, d) != "approved" {
				t.Fatal("rejected request consumed approval")
			}
		})
	}
}

func TestOpenShellPolicyOriginalUnrelatedHoldCannotBeRepurposed(t *testing.T) {
	s, gw := newSessionExecServer(t)
	d := sessionExecPostOK(t, s, "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": nativeOpenClawSession(t, "hold-session"), "agent_id": "inst_1", "tool": "exec", "tool_call_id": "held-call", "params": map[string]any{"command": "printf fixture"}})
	sessionExecPostOK(t, s, "/v1/hold/"+d["receipt_id"].(string), s.bootAdmin, map[string]any{"approve": true, "actor_id": "fixture-admin"})
	d["fixture_params"] = map[string]any{"command": "printf fixture"}
	code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
	if code != 403 || gw.setCalls != 0 {
		t.Fatal("unrelated approved exec authorized policy mutation")
	}
}

func TestOpenShellPolicyGrantRevocationAtPrewriteRejects(t *testing.T) {
	s, gw := newSessionExecServer(t)
	d := sessionExecApproveHold(t, s)
	reads := 0
	runner := gw.runner()
	s.d.Openshell.Runner = func(args []string) (int, string, string) {
		rc, out, errout := runner(args)
		if len(args) > 1 && args[0] == "policy" && args[1] == "get" {
			reads++
			if reads == 2 {
				g := s.d.Store.ActiveGrant("openclaw", "inst_1")
				if g == nil {
					t.Fatal("missing grant")
				}
				revoked, err := grant.Revoke(*g, s.d.Key)
				if err != nil {
					t.Fatal(err)
				}
				if err = s.d.Store.PutGrant(revoked); err != nil {
					t.Fatal(err)
				}
			}
		}
		return rc, out, errout
	}
	code, out := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
	if code < 400 || out["ok"] == true || gw.setCalls != 0 {
		t.Fatalf("revoked grant wrote policy: %d %v writes=%d", code, out, gw.setCalls)
	}
}

func TestOpenShellPolicyEvidenceFailureIsNotSuccess(t *testing.T) {
	s, gw := newSessionExecServer(t)
	d := sessionExecApproveHold(t, s)
	evidence := filepath.Join(s.d.Store.Dir, "evidence")
	runner := gw.runner()
	s.d.Openshell.Runner = func(args []string) (int, string, string) {
		rc, out, errout := runner(args)
		if len(args) > 1 && args[0] == "policy" && args[1] == "set" && rc == 0 {
			if err := os.Rename(evidence, evidence+"-preserved"); err != nil && !os.IsNotExist(err) {
				t.Fatal(err)
			}
			if err := os.WriteFile(evidence, []byte("blocked directory"), 0600); err != nil {
				t.Fatal(err)
			}
		}
		return rc, out, errout
	}
	code, out := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
	if code != 503 || out["ok"] != false || out["policy_applied"] != true || gw.setCalls != 1 {
		t.Fatalf("write failure misreported: %d %v", code, out)
	}
	if err := os.Remove(evidence); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(evidence+"-preserved", evidence); err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	reservation := out["reservation"].(map[string]any)
	if got := sessionExecReservationStatus(t, s, d, reservation); got != "uncertain" {
		t.Fatalf("evidence failure erased uncertainty: %s", got)
	}
}

func TestOpenShellPolicyConcurrentReplayOnlyWritesOnce(t *testing.T) {
	s, gw := newSessionExecServer(t)
	d := sessionExecApproveHold(t, s)
	var wg sync.WaitGroup
	codes := make(chan int, 2)
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
			codes <- code
		}()
	}
	wg.Wait()
	close(codes)
	counts := map[int]int{}
	for code := range codes {
		counts[code]++
	}
	if counts[200] != 1 || counts[409] != 1 || gw.setCalls != 1 {
		t.Fatalf("replay: %v writes=%d", counts, gw.setCalls)
	}
}

func TestOpenShellPolicyLoadTimeoutAfterWriteRemainsUncertain(t *testing.T) {
	s, gw := newSessionExecServer(t)
	d := sessionExecApproveHold(t, s)
	runner := gw.runner()
	s.d.Openshell.Runner = func(args []string) (int, string, string) {
		rc, out, errout := runner(args)
		if len(args) > 1 && args[0] == "policy" && args[1] == "set" && rc == 0 {
			return 124, out, "policy load timeout"
		}
		return rc, out, errout
	}
	code, out := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
	if code != 502 || out["execution_uncertain"] != true || gw.setCalls != 1 {
		t.Fatalf("load timeout misreported: %d %v", code, out)
	}
	status := sessionExecReservationStatus(t, s, d, out["reservation"].(map[string]any))
	if status != "uncertain" {
		t.Fatalf("status=%s", status)
	}
	code, _ = sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
	if code != 409 || gw.setCalls != 1 {
		t.Fatal("timed-out write replayed")
	}
}

func sessionPolicyWithExistingNetwork(host, binary string) string {
	return sessionExecBasePolicy + fmt.Sprintf(`network_policies:
  original_rule:
    name: original_rule
    endpoints:
    - host: %s
      port: 443
    binaries:
    - path: %s
`, host, binary)
}

func TestOpenShellPolicyUnrestorableBaseRefusedBeforeReservation(t *testing.T) {
	for _, tc := range []struct{ name, host, binary string }{
		{"other_endpoint", "other.test", "/usr/bin/curl"},
		{"other_binary", "api.github.com", "/usr/bin/wget"},
		{"unrestricted_binary", "api.github.com", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s, gw := newSessionExecServer(t)
			gw.body = sessionPolicyWithExistingNetwork(tc.host, tc.binary)
			if tc.binary == "" {
				gw.body = strings.Replace(gw.body, "    binaries:\n    - path: \n", "    binaries: []\n", 1)
			}
			before := gw.body
			d := sessionExecApproveHold(t, s)
			code, out := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
			expectedCode, expectedError := 403, "openshell_base_not_restorable"
			if tc.binary == "" {
				expectedCode, expectedError = 503, "openshell_base_unreadable"
			}
			if code != expectedCode || out["error"] != expectedError || gw.setCalls != 0 || gw.body != before {
				t.Fatalf("unrestorable base overwritten: code=%d result=%v writes=%d", code, out, gw.setCalls)
			}
			if sessionExecHoldStatus(t, s, d) != "approved" {
				t.Fatal("preflight refusal consumed approval")
			}
		})
	}
}

func TestOpenShellPolicyExistingAuthorizedBaseRoundTrip(t *testing.T) {
	s, gw := newSessionExecServer(t)
	gw.body = sessionPolicyWithExistingNetwork("api.github.com", "/usr/bin/curl")
	before, err := s.d.Openshell.ReadEffective("inst_1")
	if err != nil {
		t.Fatal(err)
	}
	d := sessionExecApproveHold(t, s)
	code, out := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
	if code != 200 || gw.setCalls != 1 {
		t.Fatalf("apply failed: %d %v", code, out)
	}
	reserve := out["reservation"].(map[string]any)
	code, out = sessionExecPost(t, s, "/v1/openshell/session-executions/rollback", s.bootAdmin, map[string]any{
		"reservation_receipt_id": reserve["reservation_receipt_id"], "action_id": d["action_id"], "decision_receipt_id": d["receipt_id"], "actor_id": "fixture-admin",
	})
	if code != 200 || gw.setCalls != 2 {
		t.Fatalf("restore failed: %d %v", code, out)
	}
	after, err := s.d.Openshell.ReadEffective("inst_1")
	if err != nil || after.PolicyDigest != before.PolicyDigest {
		t.Fatalf("base not restored: %v", err)
	}
}

func TestOpenShellPolicyBaseChangedAfterPreflightStillRefused(t *testing.T) {
	s, gw := newSessionExecServer(t)
	d := sessionExecApproveHold(t, s)
	runner := gw.runner()
	changed := false
	s.d.Openshell.Runner = func(args []string) (int, string, string) {
		rc, out, diag := runner(args)
		if len(args) > 1 && args[0] == "policy" && args[1] == "get" && !changed {
			changed = true
			// Same revision, but actual locked baseline differs from the earlier preflight.
			gw.body = sessionPolicyWithExistingNetwork("other.test", "/usr/bin/curl")
		}
		return rc, out, diag
	}
	code, out := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(d))
	if code < 400 || out["ok"] == true || gw.setCalls != 0 {
		t.Fatalf("changed base overwritten: %d %v", code, out)
	}
}
