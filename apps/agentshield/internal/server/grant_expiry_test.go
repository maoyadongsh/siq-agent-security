package server

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

func expiryFixture(t *testing.T) (*Server, *state.Store, string, int) {
	t.Helper()
	s, store := newServer(t, "block")
	// Keep the locator relative so admission evidence IDs (scoped to the source
	// locator by design) stay stable across checkout roots; contract samples
	// derived from this fixture must not embed the machine-specific abs path.
	path := filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like")
	_, admitted := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": path})
	code, created := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admitted["admission"].(map[string]any)["admission_id"], "platform": "hermes", "subject_id": "expiry-agent"})
	if code != 200 {
		t.Fatal(created)
	}
	return s, store, created["grant"].(map[string]any)["grant_id"].(string), stateRevision(t, created)
}

func TestGrantExpiryHTTPRevisionApprovalAndAudit(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	route := "/v1/grants/" + gid
	_, issued := call(t, s, "POST", route+"/challenge", token, withRevision(map[string]any{}, rev))
	ch := issued["challenge"].(map[string]any)
	body := map[string]any{"schema_version": "grant-expiry-edit/v1", "expected_revision": rev, "actor_id": "operator", "duration_seconds": 60}
	req := loopbackRequest("POST", route+"/expiry", body)
	req.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatal("decision token modified grant", w.Code)
	}
	before := time.Now().UTC()
	code, out := call(t, s, "POST", route+"/expiry", token, body)
	if code != 200 {
		t.Fatal(out)
	}
	g, seq, err := store.GetGrantWithSeq(gid)
	if err != nil || g.Status != "pending_approval" || seq != rev+1 || g.ExpiresAt == nil {
		t.Fatal(g, seq, err)
	}
	deadline, err := time.Parse(time.RFC3339Nano, *g.ExpiresAt)
	if err != nil || deadline.Before(before.Add(time.Minute)) || deadline.After(time.Now().Add(time.Minute)) {
		t.Fatal("deadline not server generated", err)
	}
	if code, _ := call(t, s, "POST", route+"/expiry", token, body); code != 409 {
		t.Fatal("stale write accepted", code)
	}
	if code, _ := call(t, s, "POST", route+"/approve", token, map[string]any{"expected_revision": seq, "actor_id": "operator", "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]}); code != 400 {
		t.Fatal("old challenge approved new deadline", code)
	}
	body["expected_revision"], body["duration_seconds"] = seq, nil
	if code, _ := call(t, s, "POST", route+"/expiry", token, body); code != 200 {
		t.Fatal("explicit unlimited refused", code)
	}
	g, seq, _ = store.GetGrantWithSeq(gid)
	if g.ExpiresAt != nil {
		t.Fatal("deadline not cleared")
	}
	_, issued = call(t, s, "POST", route+"/challenge", token, withRevision(map[string]any{}, seq))
	ch = issued["challenge"].(map[string]any)
	code, out = call(t, s, "POST", route+"/approve", token, map[string]any{"expected_revision": seq, "actor_id": "operator", "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]})
	if code != 200 {
		t.Fatal(out)
	}
	body["expected_revision"] = stateRevision(t, out)
	if code, _ := call(t, s, "POST", route+"/expiry", token, body); code != 400 {
		t.Fatal("approved grant extended", code)
	}
	events, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, ev := range events {
		if ev.Event == "grant_expiry" && ev.Target == gid && ev.ActorID == "operator" {
			count++
		}
	}
	if count != 2 {
		t.Fatalf("want two successful audited edits, got %d", count)
	}
}

func TestGrantExpiryHTTPRejectsMalformedRequests(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	for _, tc := range []struct {
		field   string
		value   any
		missing bool
	}{
		{"duration_seconds", nil, true}, {"duration_seconds", 0, false}, {"duration_seconds", 59, false},
		{"duration_seconds", 2592001, false}, {"duration_seconds", 60.5, false}, {"duration_seconds", "60", false},
		{"duration_seconds", true, false}, {"duration_seconds", []int{60}, false},
		{"schema_version", "grant-expiry-edit/v2", false}, {"actor_id", " ", false}, {"actor_id", strings.Repeat("人", 129), false},
		{"expected_revision", nil, true}, {"expected_revision", -1, false}, {"unknown", "secret-fixture", false},
	} {
		body := map[string]any{"schema_version": "grant-expiry-edit/v1", "expected_revision": rev, "actor_id": "operator", "duration_seconds": 60}
		if tc.missing {
			delete(body, tc.field)
		} else {
			body[tc.field] = tc.value
		}
		if code, out := call(t, s, "POST", "/v1/grants/"+gid+"/expiry", token, body); code != 400 {
			t.Fatal(tc, out)
		}
	}
	_, seq, _ := store.GetGrantWithSeq(gid)
	if seq != rev {
		t.Fatal("invalid input changed grant")
	}
	if code, _ := call(t, s, "POST", "/v1/grants/missing/expiry", token, nil); code != 404 {
		t.Fatal(code)
	}
}

func TestGrantExpiryAuditFailureDoesNotPublishAuthority(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	if err := os.MkdirAll(filepath.Join(store.Dir, "commit-audit", fmt.Sprintf("%s.%d.json", gid, rev+1)), 0700); err != nil {
		t.Fatal(err)
	}
	code, out := call(t, s, "POST", "/v1/grants/"+gid+"/expiry", token, map[string]any{"schema_version": "grant-expiry-edit/v1", "expected_revision": rev, "actor_id": "operator", "duration_seconds": 60})
	if code != 500 || out["error"] != "incomplete_commit" {
		t.Fatal(code, out)
	}
	if _, _, err := store.GetGrantWithSeq(gid); err == nil {
		t.Fatal("unaudited grant exposed as committed")
	}
}

func TestGrantExpiryContractSample(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/grant-expiry-edit.json")
	if err != nil {
		t.Fatal(err)
	}
	var body grantExpiryEdit
	if json.Unmarshal(raw, &body) != nil {
		t.Fatal("invalid fixture")
	}
	s, store, gid, rev := expiryFixture(t)
	if rev != *body.ExpectedRevision {
		t.Fatal("fixture must support initial grant revision")
	}
	if code, out := call(t, s, "POST", "/v1/grants/"+gid+"/expiry", token, body); code != 200 {
		t.Fatal(code, out)
	}
	g, _, err := store.GetGrantWithSeq(gid)
	if err != nil || grant.ValidateLifetime(*g, time.Now()) != nil {
		t.Fatal(err)
	}
}
