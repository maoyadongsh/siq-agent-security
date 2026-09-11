package intent

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
)

func grantSelectionFixture(t *testing.T) (*Store, Binding, *grant.Grant) {
	t.Helper()
	s := testStore(t)
	c, err := s.Issue(testContract())
	if err != nil {
		t.Fatal(err)
	}
	adm := admission.Admission{AdmissionID: "adm-selected", ContentHash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", Verdict: "admit", DeclaredFacts: []admission.DeclaredFact{{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: "read_file"}, Effect: "allow", State: "declared", Authority: "skill_manifest"}}}
	result, err := grant.Build(adm, grant.Options{Platform: c.Agent.Platform, Subject: grant.Subject{Type: "agent_instance", ID: c.Agent.ID}, Now: time.Date(2026, 9, 10, 0, 0, 0, 0, time.UTC), Key: s.key})
	if err != nil {
		t.Fatal(err)
	}
	g, err := grant.Approve(result.Grant, grant.Approval{ActorType: "human", ActorID: "fixture-operator", ApprovedAt: "2026-09-10T00:00:00Z", Channel: "console"}, s.key)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.MarkDeployed(g, s.key)
	if err != nil {
		t.Fatal(err)
	}
	s.grants = func(id string) (*grant.Grant, int, error) {
		if id != g.GrantID {
			return nil, 0, os.ErrNotExist
		}
		return &g, 3, nil
	}
	return s, Binding{Platform: c.Agent.Platform, AgentID: c.Agent.ID, IntentID: c.IntentID, SessionID: "selected-session"}, &g
}

func TestGrantSelectionImmutableReplayAndRestart(t *testing.T) {
	s, input, g := grantSelectionFixture(t)
	b, err := s.BindWithGrant(input, g.GrantID, 3)
	if err != nil {
		t.Fatal(err)
	}
	if b.GrantRef == nil || b.GrantRef.AdmissionID != g.AdmissionID {
		t.Fatal("missing signed selection")
	}
	retry, err := s.BindWithGrant(input, g.GrantID, 3)
	if err != nil || retry.Signature != b.Signature {
		t.Fatal("non-idempotent selection", err)
	}
	_, err = s.Bind(input)
	assertCode(t, err, "intent_binding_conflict")
	_, err = s.BindWithGrant(input, g.GrantID, 2)
	assertCode(t, err, "intent_grant_revision_conflict")
	_, err = s.Bind(b)
	assertCode(t, err, "intent_invalid_grant_selection")
	other := *g
	other.GrantID = "other-grant"
	// A caller cannot make a different Grant selectable by changing unsigned fields.
	s.grants = func(string) (*grant.Grant, int, error) { return &other, 3, nil }
	_, _, err = s.ResolveBinding(input.Platform, input.SessionID, input.AgentID)
	assertCode(t, err, "intent_grant_signature_invalid")
	s.grants = func(string) (*grant.Grant, int, error) { return g, 3, nil }
	reopened, err := Open(filepath.Dir(s.dir), s.key, s.grants)
	if err != nil {
		t.Fatal(err)
	}
	_, resolved, err := reopened.ResolveBinding(input.Platform, input.SessionID, input.AgentID)
	if err != nil || resolved.SelectedGrant == nil || resolved.SelectedGrant.GrantID != g.GrantID {
		t.Fatal("selection not restored", err)
	}
	withoutResolver, err := Open(filepath.Dir(s.dir), s.key)
	if err != nil {
		t.Fatal(err)
	}
	_, _, err = withoutResolver.ResolveBinding(input.Platform, input.SessionID, input.AgentID)
	assertCode(t, err, "intent_grant_resolver_unavailable")
}

func TestGrantSelectionRevocationMutationAndMissingFailClosed(t *testing.T) {
	for _, kind := range []string{"revoked", "permission_changed", "missing", "wrong_subject"} {
		t.Run(kind, func(t *testing.T) {
			s, input, g := grantSelectionFixture(t)
			if _, err := s.BindWithGrant(input, g.GrantID, 3); err != nil {
				t.Fatal(err)
			}
			want := "intent_grant_inactive"
			switch kind {
			case "revoked":
				out, err := grant.Revoke(*g, s.key)
				if err != nil {
					t.Fatal(err)
				}
				*g = out
			case "missing":
				s.grants = func(string) (*grant.Grant, int, error) { return nil, 0, errors.New("private store detail") }
				want = "intent_grant_unavailable"
			case "permission_changed", "wrong_subject":
				g.Facts[0].Resource.Value = "write_file"
				if kind == "wrong_subject" {
					g.Subject.ID = "other"
					want = "intent_grant_subject_mismatch"
				} else {
					want = "intent_grant_digest_mismatch"
				}
				// Sign changed authoritative state to distinguish validity from stale limits.
				raw, _ := json.Marshal(g)
				decoded, _ := canon.Decode(raw)
				document := decoded.(map[string]any)
				delete(document, "signature")
				g.Signature, _ = s.key.SignCanonical(document)
			}
			_, _, err := s.ResolveBinding(input.Platform, input.SessionID, input.AgentID)
			assertCode(t, err, want)
		})
	}
}

func TestGrantSelectionClampsDeadlineAndChecksBindingIdentity(t *testing.T) {
	s, input, g := grantSelectionFixture(t)
	end := time.Now().Add(time.Hour).UTC().Format(time.RFC3339Nano)
	g.ExpiresAt = &end
	raw, _ := json.Marshal(g)
	decoded, _ := canon.Decode(raw)
	document := decoded.(map[string]any)
	delete(document, "signature")
	g.Signature, _ = s.key.SignCanonical(document)
	b, err := s.BindWithGrant(input, g.GrantID, 3)
	if err != nil || b.ExpiresAt != end {
		t.Fatal("binding outlives grant", err)
	}
	input.SessionID = "wrong-subject"
	input.AgentID = "other"
	_, err = s.BindWithGrant(input, g.GrantID, 3)
	assertCode(t, err, "intent_grant_subject_mismatch")
}

func TestGrantSelectionSharedContractSamples(t *testing.T) {
	s, input, g := grantSelectionFixture(t)
	b, err := s.BindWithGrant(input, g.GrantID, 3)
	if err != nil {
		t.Fatal(err)
	}
	stored, err := s.GetBinding(b.BindingID)
	if err != nil || stored.Signature != b.Signature {
		t.Fatal("signed output not readable", err)
	}
	// Normalize only the issuance clock and its dependent signature for a fixed
	// public fixture; the actual returned record was independently verified above.
	b.BoundAt = "2026-09-10T00:00:00Z"
	b.Signature, err = s.key.SignCanonical(bindingMap(b))
	if err != nil {
		t.Fatal(err)
	}
	request := map[string]any{"schema_version": "intent-grant-bind/v1", "platform": input.Platform, "session_id": input.SessionID, "agent_id": input.AgentID, "intent_id": input.IntentID, "grant_id": g.GrantID, "expected_grant_revision": 3}
	for name, value := range map[string]any{"intent-grant-bind": request, "intent-grant-binding": b} {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := filepath.Join("..", "..", "testdata", "contracts", name+".json")
		if os.Getenv("SIQ_UPDATE_GRANT_BINDING_FIXTURES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(expected, raw) {
			t.Fatal("shared contract output mismatch", name)
		}
	}
}

func TestGrantSelectionAllowsReadbackEvidenceWithoutChangingPermission(t *testing.T) {
	s, input, g := grantSelectionFixture(t)
	if _, err := s.BindWithGrant(input, g.GrantID, 3); err != nil {
		t.Fatal(err)
	}
	updated, err := grant.MarkEffective(*g, grant.Readback{Backend: "fixture-backend", Revision: "r2", EvidenceID: "ev-readback"}, map[string]string{g.Facts[0].FactID: "ev-readback"}, s.key)
	if err != nil {
		t.Fatal(err)
	}
	*g = updated
	_, b, err := s.ResolveBinding(input.Platform, input.SessionID, input.AgentID)
	if err != nil || b.SelectedGrant.Status != "effective" {
		t.Fatal("unchanged permissions invalidated by readback", err)
	}
}
