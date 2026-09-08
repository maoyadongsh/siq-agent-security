package intent

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

func contextFixture() trustedcontext.Assertion {
	subject := trustedcontext.Subject{Platform: "hermes", SessionID: "s1", AgentID: "a-1"}
	binding, _ := trustedcontext.RequestBinding(subject, "task-1", "read_file", "tc-1", map[string]any{"path": "/work/report"})
	return trustedcontext.Assertion{SchemaVersion: "context-assertion/v1", AssertionID: "ctx-1", IssuerID: "local-admin", Subject: subject, TaskID: "task-1", Claims: trustedcontext.Claims{WorkspaceRoot: "/work"}, IssuedAt: "2026-01-01T00:00:00Z", ExpiresAt: "2026-01-02T00:00:00Z", RequestBinding: binding}
}
func TestContextIntegrityScopeReplayAndExpiry(t *testing.T) {
	s := testStore(t)
	a, err := s.IssueContext(contextFixture())
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	check := func(a *trustedcontext.Assertion, subject trustedcontext.Subject, task, call, path string, at time.Time) error {
		return a.Check(subject, task, "read_file", call, map[string]any{"path": path}, at)
	}
	if err := check(a, a.Subject, a.TaskID, "tc-1", "/work/report", now); err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct{ task, call, path string }{
		{"other-task", "tc-1", "/work/report"}, {"task-1", "tc-2", "/work/report"}, {"task-1", "tc-1", "/secret/report"},
	} {
		if check(a, a.Subject, c.task, c.call, c.path, now) == nil {
			t.Fatal("replay accepted", c)
		}
	}
	for _, edit := range []func(*trustedcontext.Subject){func(s *trustedcontext.Subject) { s.SessionID = "other" }, func(s *trustedcontext.Subject) { s.AgentID = "other" }, func(s *trustedcontext.Subject) { s.Platform = "other" }} {
		subject := a.Subject
		edit(&subject)
		if check(a, subject, a.TaskID, "tc-1", "/work/report", now) == nil {
			t.Fatal("scope replay accepted")
		}
	}
	if check(a, a.Subject, a.TaskID, "tc-1", "/work/report", now.Add(12*time.Hour)) == nil {
		t.Fatal("expiry boundary accepted")
	}
	if check(a, a.Subject, a.TaskID, "tc-1", "/work/report", now.Add(-24*time.Hour)) == nil {
		t.Fatal("future assertion accepted")
	}
	reopened, err := Open(filepath.Dir(s.dir), s.key)
	if err != nil {
		t.Fatal(err)
	}
	if recovered, err := reopened.GetContext(a.AssertionID); err != nil || recovered.Signature != a.Signature {
		t.Fatal("restart lost context", err)
	}
	if _, err = s.IssueContext(contextFixture()); err == nil {
		t.Fatal("immutable record replaced")
	}
	for _, edit := range []func(*trustedcontext.Assertion){func(a *trustedcontext.Assertion) { a.Claims.WorkspaceRoot = "/secret" }, func(a *trustedcontext.Assertion) { a.IssuerID = "forged" }, func(a *trustedcontext.Assertion) { a.Signature = string(bytes.Repeat([]byte{'0'}, 128)) }} {
		bad := *a
		edit(&bad)
		raw, _ := json.Marshal(bad)
		if err := os.WriteFile(filepath.Join(s.contextDir(), a.AssertionID+".json"), raw, 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := s.GetContext(a.AssertionID); err == nil {
			t.Fatal("tampered assertion trusted")
		}
	}
}
func TestContextPublicationConcurrencyAndSample(t *testing.T) {
	s := testStore(t)
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			a := contextFixture()
			a.AssertionID = fmt.Sprintf("ctx-%d", i)
			if _, err := s.IssueContext(a); err != nil {
				t.Error(err)
				return
			}
			if _, err := s.GetContext(a.AssertionID); err != nil {
				t.Error(err)
			}
		}(i)
	}
	wg.Wait()
	a, err := s.GetContext("ctx-1")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.MarshalIndent(a, "", "  ")
	path := "../../testdata/contracts/context-assertion.sample.json"
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, append(raw, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(bytes.TrimSpace(want), raw) {
		t.Fatal("context sample differs", err)
	}
}
func TestContextCapacityAndMalformedStorageFailClosed(t *testing.T) {
	s := testStore(t)
	for i := 0; i < maxRecords; i++ {
		if err := os.WriteFile(filepath.Join(s.contextDir(), fmt.Sprintf("cap-%d.json", i)), []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := s.IssueContext(contextFixture()); err == nil {
		t.Fatal("capacity silently exceeded")
	}
	if _, err := s.GetContext("cap-0"); err == nil {
		t.Fatal("unsigned state accepted")
	}
	if _, err := s.GetContext("../intents/int-test"); err == nil {
		t.Fatal("path traversal accepted")
	}
}
