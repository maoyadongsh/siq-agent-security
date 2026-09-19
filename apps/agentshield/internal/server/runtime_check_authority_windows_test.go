package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/intent"
	"testing"
	"time"
)

func TestWindowsRuntimeCheckRejectsOrdinaryIssuerBindingAndObserver(t *testing.T) {
	s := newRuntimeCheckHTTPServer(t)
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", "intent-contract.v5.sample.json"))
	if err != nil {
		t.Fatal(err)
	}
	var c intent.Contract
	if err = json.Unmarshal(raw, &c); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	c.IssuedAt = now.Format(time.RFC3339Nano)
	c.ValidFrom = c.IssuedAt
	c.ExpiresAt = now.Add(120 * time.Second).Format(time.RFC3339Nano)
	c.Digest = ""
	c.Signature = ""
	c.SigningSchema = ""
	if code, body := call(t, s, "POST", "/v1/intents", token, c); code != 400 || body["error"] != "intent_runtime_check_issuer_required" {
		t.Fatal(code, body)
	}
	// Internal synthetic issuance exists only to prove the public binding and
	// observer edges reject this version; it is not an active Manager check.
	issued, err := s.intents.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	body := map[string]any{"schema_version": "intent-grant-bind/v1", "grant_id": "grt-unused", "expected_grant_revision": 0, "platform": "hermes", "session_id": "ordinary", "agent_id": c.Agent.ID, "intent_id": c.IntentID}
	if code, out := call(t, s, "POST", "/v1/intent-bindings", token, body); code != 400 || out["error"] != "intent_runtime_check_binding_required" {
		t.Fatal(code, out)
	}
	if bindings, err := s.intents.ListBindings(); err != nil || len(bindings) != 0 {
		t.Fatal("ordinary binding created", err)
	}
	if _, err := s.fileActionProfile(effectevidence.Action{IntentID: issued.IntentID, IntentDigest: issued.Digest, TaskID: issued.TaskID, AgentID: issued.Agent.ID, Platform: "hermes", SessionID: "ordinary"}); err == nil {
		t.Fatal("independent observer accepted self-check authority")
	}
	for _, credential := range []string{token, s.bootAdmin} {
		for _, path := range []string{"/v1/decide", "/v1/observe"} {
			out := sessionRequest(t, s, "POST", path, map[string]any{"platform": "hermes", "agent_id": c.Agent.ID, "session_id": "ordinary", "tool": "read_file", "tool_call_id": "borrow", "params": map[string]any{"path": "C:/Synthetic/first.txt"}}, credential, nil, nil)
			if out.Code != 401 && out.Code != 403 {
				t.Fatalf("ordinary credential borrowed self-check: %s %d", path, out.Code)
			}
		}
	}
}
