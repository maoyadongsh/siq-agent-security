package intent

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"sync"
	"testing"
	"time"
)

func testContract() Contract {
	return Contract{SchemaVersion: "intent/v2", IntentID: "int-test", TaskID: "task-1", Principal: Principal{"user", "u-1"}, Agent: Agent{"a-1", "hermes"}, Purpose: "read approved report", AllowedTools: []string{"read_file"}, AllowedEffects: []string{"file.read"}, ResourceConstraints: []ResourceConstraint{}, ParameterConstraints: []ParameterConstraint{}, IssuedAt: "2026-01-01T00:00:00Z", ValidFrom: "2026-01-01T00:00:00Z", ExpiresAt: "2099-01-01T00:00:00Z", Authority: Authority{"local-admin", "r1", []string{}}}
}
func testStore(t *testing.T) *Store {
	t.Helper()
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func assertCode(t *testing.T, err error, code string) {
	t.Helper()
	var v *Violation
	if !errors.As(err, &v) || v.Code != code {
		t.Fatalf("got %v want %s", err, code)
	}
}
func TestStoreIntegrityAndImmutability(t *testing.T) {
	s := testStore(t)
	c := testContract()
	issued, err := s.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	retry, err := s.Issue(c)
	if err != nil || retry.Digest != issued.Digest {
		t.Fatal("retry", err)
	}
	c.Purpose = "other"
	_, err = s.Issue(c)
	assertCode(t, err, "intent_immutable_conflict")
	for _, which := range []string{"digest", "signature"} {
		t.Run(which, func(t *testing.T) {
			copy := *issued
			if which == "digest" {
				copy.Purpose = "tampered"
			} else {
				copy.Signature = string(bytes.Repeat([]byte{'0'}, 128))
			}
			raw, _ := json.Marshal(copy)
			p, _ := s.path(copy.IntentID)
			if err := os.WriteFile(p, raw, 0600); err != nil {
				t.Fatal(err)
			}
			_, err := s.Get(copy.IntentID)
			assertCode(t, err, "intent_"+which+map[string]string{"digest": "_mismatch", "signature": "_invalid"}[which])
		})
	}
}
func TestBindingAuthorityAndConcurrency(t *testing.T) {
	s := testStore(t)
	c, err := s.Issue(testContract())
	if err != nil {
		t.Fatal(err)
	}
	req := Binding{Platform: "hermes", SessionID: "s1", AgentID: "a-1", IntentID: c.IntentID}
	bad := req
	bad.AgentID = "a-2"
	_, err = s.Bind(bad)
	assertCode(t, err, "intent_agent_mismatch")
	bad = req
	bad.TaskID = "other"
	_, err = s.Bind(bad)
	assertCode(t, err, "intent_task_mismatch")
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := s.Bind(req); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	list, err := s.ListBindings()
	if err != nil || len(list) != 1 {
		t.Fatalf("bindings: %v %v", list, err)
	}
	other := testContract()
	other.IntentID = "int-other"
	if _, err = s.Issue(other); err != nil {
		t.Fatal(err)
	}
	req.IntentID = other.IntentID
	_, err = s.Bind(req)
	assertCode(t, err, "intent_binding_conflict")
	reopened, err := Open(filepath.Dir(s.dir), s.key)
	if err != nil {
		t.Fatal(err)
	}
	resolved, _, err := reopened.ResolveBinding("hermes", "s1", "a-1")
	if err != nil || resolved.IntentID != c.IntentID {
		t.Fatal(err)
	}
	// Signed expired binding must remain a denial after restart, never become unbound.
	b := list[0]
	b.ExpiresAt = "2020-01-01T00:00:00Z"
	b.Signature, _ = s.key.SignCanonical(bindingMap(b))
	raw, _ := json.Marshal(b)
	p, _ := s.bindingPath(b.BindingID)
	if err := os.WriteFile(p, raw, 0600); err != nil {
		t.Fatal(err)
	}
	_, _, err = reopened.ResolveBinding("hermes", "s1", "a-1")
	assertCode(t, err, "intent_expired")
}
func TestEvidenceAndInvalidContracts(t *testing.T) {
	s := testStore(t)
	cases := []struct {
		name, code string
		edit       func(*Contract)
	}{
		{"missing evidence", "intent_evidence_missing", func(c *Contract) { c.Authority.EvidenceIDs = []string{"ev-made-up"} }},
		{"time", "intent_invalid_time_window", func(c *Contract) { c.ExpiresAt = "bad" }},
		{"pointer", "intent_invalid_parameter_pointer", func(c *Contract) {
			c.ParameterConstraints = []ParameterConstraint{{Path: "/bad~2", Operator: "equals", Value: "x"}}
		}},
		{"operator", "intent_invalid_constraint", func(c *Contract) { c.ParameterConstraints = []ParameterConstraint{{Path: "/x", Operator: "execute"}} }},
		{"regex", "intent_invalid_regex", func(c *Contract) {
			c.ParameterConstraints = []ParameterConstraint{{Path: "/x", Operator: "regex", Value: "["}}
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c := testContract()
			tc.edit(&c)
			_, err := s.Issue(c)
			assertCode(t, err, tc.code)
		})
	}
	c := testContract()
	c.Authority.EvidenceIDs = []string{"external:https://example.com/approval/1"}
	if _, err := s.Issue(c); err != nil {
		t.Fatal(err)
	}
}
func TestV2ConstraintAuthorization(t *testing.T) {
	now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
	c := testContract()
	c.ResourceConstraints = []ResourceConstraint{{"filesystem", "prefix", "/company-a/"}}
	for _, p := range []string{"/company-a/report.txt", "/company-a/sub/../report.txt"} {
		if err := c.Authorize("hermes", "a-1", "", "read_file", map[string]any{"path": p}, now); err != nil {
			t.Fatal(err)
		}
	}
	for _, p := range []string{"/company-b/secret", "/company-a-evil/report", "/company-a/../secret", "relative.txt"} {
		assertCode(t, c.Authorize("hermes", "a-1", "", "read_file", map[string]any{"path": p}, now), "intent_resource_not_allowed")
	}
	c.ResourceConstraints = []ResourceConstraint{}
	c.ParameterConstraints = []ParameterConstraint{{Path: "/request/body/users/0/a~1b", Operator: "one_of", Values: []any{"alice"}}}
	params := map[string]any{"request": map[string]any{"body": map[string]any{"users": []any{map[string]any{"a/b": "alice"}}}}}
	if err := c.Authorize("hermes", "a-1", "", "read_file", params, now); err != nil {
		t.Fatal(err)
	}
	assertCode(t, c.Authorize("hermes", "a-1", "", "read_file", map[string]any{}, now), "intent_parameter_violation")
	c = testContract()
	c.AllowedTools = []string{"Bash"}
	c.AllowedEffects = []string{"process.exec"}
	assertCode(t, c.Authorize("hermes", "a-1", "", "Bash", map[string]any{"command": "curl https://example.com"}, now), "intent_effect_not_allowed")
	c.AllowedTools = []string{"opaque"}
	c.AllowedEffects = []string{"unknown"}
	assertCode(t, c.Authorize("hermes", "a-1", "", "opaque", nil, now), "runtime_effect_unknown")
}
