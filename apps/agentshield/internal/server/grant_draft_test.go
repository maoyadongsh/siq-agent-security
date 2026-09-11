package server

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

func draftSource(t *testing.T) (*Server, *state.Store, string, int) {
	t.Helper()
	s, store, id, rev := expiryFixture(t)
	code, approved := approveChallenged(t, s, id, "operator", rev)
	if code != 200 {
		t.Fatal(approved)
	}
	code, deployed := call(t, s, "POST", "/v1/grants/"+id+"/deploy", token, map[string]any{"actor_id": "operator", "expected_revision": stateRevision(t, approved)})
	if code != 200 {
		t.Fatal(deployed)
	}
	return s, store, id, stateRevision(t, deployed)
}
func draftBody(rev int) map[string]any {
	return map[string]any{"schema_version": "grant-draft-create/v1", "expected_revision": rev, "actor_id": "operator", "request_id": "gd-" + strings.Repeat("a", 32)}
}

func TestGrantDraftHTTPIndependentIdempotentAndAudited(t *testing.T) {
	s, store, id, rev := draftSource(t)
	source, _, _ := store.GetGrantWithSeq(id)
	before, _ := json.Marshal(source)
	route := "/v1/grants/" + id + "/draft"
	body := draftBody(rev)
	var wg sync.WaitGroup
	ids := make(chan string, 8)
	for range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			code, out := call(t, s, "POST", route, token, body)
			if code != 200 {
				t.Errorf("parallel draft %d %v", code, out)
				return
			}
			ids <- out["grant"].(map[string]any)["grant_id"].(string)
		}()
	}
	wg.Wait()
	close(ids)
	createdID := ""
	count := 0
	for value := range ids {
		if createdID != "" && value != createdID {
			t.Fatal("duplicate drafts")
		}
		createdID = value
		count++
	}
	if count != 8 {
		t.Fatal("requests failed")
	}
	created, seq, err := store.GetGrantWithSeq(createdID)
	if err != nil || seq != 0 || created.Status != "pending_approval" || !grant.Verify(s.d.Key.Public(), *created) {
		t.Fatal(err, created)
	}
	if created.GrantID == id || created.DesiredPolicyRef.PolicyID == source.DesiredPolicyRef.PolicyID {
		t.Fatal("source namespace reused")
	}
	source, sourceRev, _ := store.GetGrantWithSeq(id)
	after, _ := json.Marshal(source)
	if sourceRev != rev || string(before) != string(after) {
		t.Fatal("source modified")
	}
	code, edit := call(t, s, "POST", "/v1/grants/"+createdID+"/expiry", token, map[string]any{"schema_version": "grant-expiry-edit/v1", "expected_revision": seq, "actor_id": "operator", "duration_seconds": 600})
	if code != 200 {
		t.Fatal(edit)
	}
	code, retry := call(t, s, "POST", route, token, body)
	if code != 200 || retry["reused"] != true || stateRevision(t, retry) != stateRevision(t, edit) {
		t.Fatal("retry overwrote edited draft", retry)
	}
	events, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	drafts := 0
	for _, e := range events {
		if e.Event == "grant_draft" {
			drafts++
			if e.Target != createdID || !strings.Contains(e.Note, "source="+id) || e.ActorID != "operator" {
				t.Fatal("missing provenance audit", e)
			}
		}
	}
	if drafts != 1 {
		t.Fatal("duplicate audit", drafts)
	}
}
func TestGrantDraftHTTPRejectsStaleMalformedAndNonAdmin(t *testing.T) {
	s, store, id, rev := draftSource(t)
	route := "/v1/grants/" + id + "/draft"
	req := loopbackRequest("POST", route, draftBody(rev))
	req.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatal("decision credential drafted permissions", w.Code)
	}
	good, _ := json.Marshal(draftBody(rev))
	for _, raw := range []string{`{}`, strings.Replace(string(good), `"actor_id":"operator"`, `"actor_id":null`, 1), strings.Replace(string(good), `"actor_id":"operator"`, `"actor_id":"operator","actor_id":"other"`, 1), strings.Replace(string(good), `"actor_id"`, `"Actor_ID"`, 1), strings.Replace(string(good), `"actor_id":"operator"`, `"actor_id":"operator","grant_id":"forged"`, 1), string(good) + ` {}`, strings.Repeat(" ", 16385)} {
		if code, _ := call(t, s, "POST", route, token, raw); code != 400 {
			t.Fatal("malformed request accepted", code)
		}
	}
	stale := draftBody(rev - 1)
	if code, _ := call(t, s, "POST", route, token, stale); code != 409 {
		t.Fatal("stale source accepted", code)
	}
	source, _, _ := store.GetGrantWithSeq(id)
	policy := filepath.Join(store.Dir, "policies", fmt.Sprintf("%s.v%d.json", source.DesiredPolicyRef.PolicyID, source.DesiredPolicyRef.Version))
	if err := os.WriteFile(policy, []byte(`{}`), 0600); err != nil {
		t.Fatal(err)
	}
	if code, _ := call(t, s, "POST", route, token, draftBody(rev)); code != 409 {
		t.Fatal("bad policy copied", code)
	}
	grants, _ := store.ListGrants()
	if len(grants) != 1 {
		t.Fatal("rejection published draft")
	}
}
func TestGrantDraftContractSamples(t *testing.T) {
	s, store, id, rev := draftSource(t)
	body := draftBody(rev)
	code, out := call(t, s, "POST", "/v1/grants/"+id+"/draft", token, body)
	if code != 200 {
		t.Fatal(out)
	}
	g, _, _ := store.GetGrantWithSeq(out["grant"].(map[string]any)["grant_id"].(string))
	if !grant.Verify(s.d.Key.Public(), *g) {
		t.Fatal("invalid runtime signature")
	}
	// Only the generated timestamp/signature vary for the exact fixture inputs.
	projected := out["grant"].(map[string]any)
	projected["created_at"] = "2026-09-10T09:00:00Z"
	projected["signature"] = strings.Repeat("0", 128)
	for name, value := range map[string]any{"grant-draft-create.json": body, "grant-draft-created.json": out} {
		raw, _ := json.MarshalIndent(value, "", "  ")
		raw = append(raw, '\n')
		path := filepath.Join("..", "..", "testdata", "contracts", name)
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0644); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || string(raw) != string(expected) {
			t.Fatal("draft contract drift", name, err)
		}
	}
}
