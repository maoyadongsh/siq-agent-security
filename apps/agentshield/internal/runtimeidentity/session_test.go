package runtimeidentity

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
)

func TestSessionEnrollmentIsFixedAndScoped(t *testing.T) {
	s, req, _ := fixture(t)
	r, token := create(t, s, req)
	if _, err := s.AuthorizeSession(token, r.Platform, r.AgentID, "native-1"); err == nil {
		t.Fatal("unenrolled session accepted")
	}
	b, err := s.Enroll(token, "native-1")
	if err != nil {
		t.Fatal(err)
	}
	if b.GrantRef == nil || *b.GrantRef != r.GrantRef {
		t.Fatal("lost fixed grant")
	}
	c, err := s.intents.Get(b.IntentID)
	if err != nil {
		t.Fatal(err)
	}
	if c.Purpose != permissionPurpose || c.Principal.ID != req.ActorID || c.Authority.Revision != recordDigest(r) {
		t.Fatal("wrong authority provenance")
	}
	for _, effect := range c.AllowedEffects {
		if effect == "unknown" {
			t.Fatal("unknown effect permitted")
		}
	}
	retry, err := s.Enroll(token, "native-1")
	if err != nil || retry.Signature != b.Signature || retry.ExpiresAt != b.ExpiresAt {
		t.Fatal("non-idempotent enrollment", err)
	}
	if _, err = s.AuthorizeSession(token, r.Platform, r.AgentID, "native-1"); err != nil {
		t.Fatal(err)
	}
	for _, values := range [][3]string{{"openclaw", r.AgentID, "native-1"}, {r.Platform, "other-agent", "native-1"}, {r.Platform, r.AgentID, "native-2"}} {
		if _, err = s.AuthorizeSession(token, values[0], values[1], values[2]); err == nil {
			t.Fatal("wrong session tuple authorized")
		}
	}
	other, err := s.Enroll(token, "native-2")
	if err != nil || other.IntentID == b.IntentID || other.TaskID == b.TaskID {
		t.Fatal("sessions share authority", err)
	}
	restarted, err := Open(s.dir, s.key, s.intents, s.resolve)
	if err != nil {
		t.Fatal(err)
	}
	recovered, err := restarted.AuthorizeSession(token, r.Platform, r.AgentID, "native-1")
	if err != nil || recovered.Signature != b.Signature {
		t.Fatal("restart", err)
	}
	if _, err = s.Revoke(r.IdentityID, "operator"); err != nil {
		t.Fatal(err)
	}
	_, replacement := create(t, s, req)
	if _, err = s.AuthorizeSession(token, r.Platform, r.AgentID, "native-1"); err == nil {
		t.Fatal("revoked credential kept session")
	}
	if _, err = s.AuthorizeSession(replacement, r.Platform, r.AgentID, "native-1"); err == nil {
		t.Fatal("replacement borrowed old session")
	}
	if _, err = s.Enroll(replacement, "native-1"); err == nil {
		t.Fatal("replacement rebound old session")
	}
	if _, err = s.Enroll(replacement, "new-native-session"); err != nil {
		t.Fatal(err)
	}
}

func TestSessionRevocationAndExpiryNeverResurrect(t *testing.T) {
	for _, kind := range []string{"binding", "intent", "expiry", "grant"} {
		t.Run(kind, func(t *testing.T) {
			s, req, g := fixture(t)
			r, token := create(t, s, req)
			if kind == "expiry" {
				expired := permissionEnvelope(r, "session", g, time.Now().Add(-9*time.Hour))
				if _, err := s.intents.Issue(expired); err != nil {
					t.Fatal(err)
				}
			} else {
				b, err := s.Enroll(token, "session")
				if err != nil {
					t.Fatal(err)
				}
				switch kind {
				case "binding":
					_, err = s.intents.RevokeBinding(b.BindingID, b.IntentDigest)
				case "intent":
					_, err = s.intents.RevokeIntent(b.IntentID, b.IntentDigest)
				case "grant":
					var next grant.Grant
					next, err = grant.Revoke(*g, s.key)
					*g = next
				}
				if err != nil {
					t.Fatal(err)
				}
			}
			if _, err := s.Enroll(token, "session"); err == nil {
				t.Fatal("resurrected session")
			}
			if _, err := s.AuthorizeSession(token, r.Platform, r.AgentID, "session"); err == nil {
				t.Fatal("withdrawn authority accepted")
			}
		})
	}
}
func TestSessionInterruptedIssuanceUsesOriginalEnvelope(t *testing.T) {
	s, req, g := fixture(t)
	r, token := create(t, s, req)
	at := time.Now().Add(-time.Minute)
	c, err := s.intents.Issue(permissionEnvelope(r, "interrupted", g, at))
	if err != nil {
		t.Fatal(err)
	}
	b, err := s.Enroll(token, "interrupted")
	if err != nil {
		t.Fatal(err)
	}
	if b.IntentDigest != c.Digest || b.ExpiresAt != c.ExpiresAt {
		t.Fatal("recovery extended or replaced authority")
	}
	conflict := permissionEnvelope(r, "conflicting", g, at)
	conflict.AllowedTools = []string{"write_file"}
	if _, err = s.intents.Issue(conflict); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Enroll(token, "conflicting"); err == nil {
		t.Fatal("adopted different permission envelope")
	}
}
func TestSessionLifetimeClampedToGrantAndInputBounds(t *testing.T) {
	s, req, g := fixture(t)
	end := time.Now().Add(2 * time.Minute).UTC().Format(time.RFC3339Nano)
	g.ExpiresAt = &end
	g.Signature, _ = s.sign(*g)
	r, token := create(t, s, req)
	b, err := s.Enroll(token, strings.Repeat("会", 256))
	if err != nil {
		t.Fatal(err)
	}
	if b.ExpiresAt != end {
		t.Fatal("binding outlives grant")
	}
	for _, sid := range []string{"", strings.Repeat("会", 257), "line\nfeed", string([]byte{0xff})} {
		if _, err = s.Enroll(token, sid); err == nil {
			t.Fatal("invalid session accepted")
		}
	}
	if _, err = s.AuthorizeSession(token, r.Platform, r.AgentID, strings.Repeat("会", 256)); err != nil {
		t.Fatal(err)
	}
}
func TestSessionEnrollmentConcurrentRetries(t *testing.T) {
	s, req, _ := fixture(t)
	_, token := create(t, s, req)
	var wg sync.WaitGroup
	results := make(chan string, 10)
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			b, err := s.Enroll(token, "concurrent")
			if err != nil {
				t.Error(err)
				return
			}
			results <- b.Signature
		}()
	}
	wg.Wait()
	close(results)
	first := ""
	n := 0
	for signature := range results {
		n++
		if first == "" {
			first = signature
		}
		if signature != first {
			t.Fatal("duplicate publication")
		}
	}
	if n != 10 {
		t.Fatal("missing result")
	}
}
func TestPermissionEnvelopeRetainsDeniedAndApprovalToolSemantics(t *testing.T) {
	s, req, g := fixture(t)
	r, _ := create(t, s, req)
	g.OpenClawToolPolicy = &grant.OpenClawToolPolicy{Allow: []string{"read_file", "write_file"}, Deny: []string{"write_file"}, RequireApproval: []string{"web_fetch"}}
	c := permissionEnvelope(r, "tools", g, time.Now())
	if !reflect.DeepEqual(c.AllowedTools, []string{"read_file", "web_fetch"}) {
		t.Fatal("lost deny/approval semantics", c.AllowedTools)
	}
}
func TestSessionSharedRequestFixture(t *testing.T) {
	value := EnrollRequest{"local-runtime-session-enroll/v1", "native-session-fixture"}
	b, _ := json.MarshalIndent(value, "", "  ")
	b = append(b, '\n')
	path := filepath.Join("..", "..", "testdata", "contracts", "local-runtime-session-enroll.json")
	if os.Getenv("SIQ_UPDATE_RUNTIME_IDENTITY_FIXTURES") == "1" {
		if err := os.WriteFile(path, b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(path)
	if err != nil || string(want) != string(b) {
		t.Fatal("request fixture mismatch", err)
	}
}

func TestDifferentInstancesCannotBorrowEachOthersSessions(t *testing.T) {
	s, req, g := fixture(t)
	other := *g
	other.GrantID = "grt-other-instance"
	otherInstance := "hi-" + strings.Repeat("2", 32)
	other.Subject.ID, _ = AgentID(otherInstance)
	other.Signature, _ = s.sign(other)
	authority, err := intent.Open(s.dir, s.key, func(id string) (*grant.Grant, int, error) {
		if id == g.GrantID {
			return g, 3, nil
		}
		if id == other.GrantID {
			return &other, 3, nil
		}
		return nil, 0, os.ErrNotExist
	})
	if err != nil {
		t.Fatal(err)
	}
	s.intents = authority
	s.resolve = func(id string) error {
		if id == req.InstanceID || id == otherInstance {
			return nil
		}
		return ErrUnavailable
	}
	first, firstToken := create(t, s, req)
	otherReq := req
	otherReq.InstanceID = otherInstance
	otherReq.GrantID = other.GrantID
	second, secondToken := create(t, s, otherReq)
	a, err := s.Enroll(firstToken, "same-native-id")
	if err != nil {
		t.Fatal(err)
	}
	b, err := s.Enroll(secondToken, "same-native-id")
	if err != nil {
		t.Fatal(err)
	}
	if a.IntentID == b.IntentID || a.GrantRef.GrantID == b.GrantRef.GrantID {
		t.Fatal("instances share authority")
	}
	for _, check := range []struct{ token, agent string }{{firstToken, second.AgentID}, {secondToken, first.AgentID}} {
		if _, err := s.AuthorizeSession(check.token, "hermes", check.agent, "same-native-id"); err == nil {
			t.Fatal("cross-instance credential accepted")
		}
	}
	if _, err := s.AuthorizeSession(firstToken, "hermes", first.AgentID, "same-native-id"); err != nil {
		t.Fatal(err)
	}
	if _, err := s.AuthorizeSession(secondToken, "hermes", second.AgentID, "same-native-id"); err != nil {
		t.Fatal(err)
	}
}
