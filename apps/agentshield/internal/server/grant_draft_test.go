package server

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

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

// A draft id whose commit journal and grant file exist but whose done marker is
// missing is a torn or in-flight commit. The create route must never 200 over it,
// must not overwrite or re-audit it, and must resolve to the committed draft once
// the commit settles. This deterministically exercises the commit visibility
// window that CI hit with 409 grant_draft_unavailable under parallel creates.
func TestGrantDraftHTTPTornCommitRefusedThenSettled(t *testing.T) {
	s, store, id, rev := draftSource(t)
	source, _, err := store.GetGrantWithSeq(id)
	if err != nil {
		t.Fatal(err)
	}
	policy, err := store.GrantPolicy(*source)
	if err != nil {
		t.Fatal(err)
	}
	requestID := "gd-" + strings.Repeat("b", 32)
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d\x00%s\x00%s", id, rev, "operator", requestID)))
	draftID := "grt-d-" + hex.EncodeToString(digest[:])
	won, err := grant.DraftFrom(*source, policy, draftID, time.Date(2026, 9, 11, 1, 0, 0, 0, time.UTC), s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	journal, err := json.Marshal(map[string]any{"schema": "grant_commit/v1", "commit": state.GrantCommit{
		Grant:            won.Grant,
		ExpectedRevision: -1,
		DesiredPolicy:    won.DesiredPolicy,
		Audit:            &state.AuditEvent{At: "2026-09-11T01:00:00Z", Event: "grant_draft", ActorID: "operator", Target: draftID, Note: "source=" + id},
	}})
	if err != nil {
		t.Fatal(err)
	}
	grantRaw, err := json.MarshalIndent(won.Grant, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	commits := filepath.Join(store.Dir, "commits")
	if err := os.MkdirAll(commits, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(store.Dir, "grants"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(commits, draftID+".0.prepare.json"), journal, 0o600); err != nil {
		t.Fatal(err)
	}
	grantPath := filepath.Join(store.Dir, "grants", draftID+".0.json")
	if err := os.WriteFile(grantPath, grantRaw, 0o600); err != nil {
		t.Fatal(err)
	}
	body := map[string]any{"schema_version": "grant-draft-create/v1", "expected_revision": rev, "actor_id": "operator", "request_id": requestID}
	code, out := call(t, s, "POST", "/v1/grants/"+id+"/draft", token, body)
	if code != 409 {
		t.Fatal("torn commit accepted", code, out)
	}
	if raw, _ := os.ReadFile(grantPath); !bytes.Equal(raw, grantRaw) {
		t.Fatal("torn commit overwritten")
	}
	if _, err := os.Lstat(filepath.Join(store.Dir, "commit-audit", draftID+".0.json")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("refused request wrote commit audit")
	}
	sum := sha256.Sum256(journal)
	if err := os.WriteFile(filepath.Join(commits, draftID+".0.done.json"), []byte(hex.EncodeToString(sum[:])+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	code, out = call(t, s, "POST", "/v1/grants/"+id+"/draft", token, body)
	if code != 200 || out["reused"] != true {
		t.Fatal("settled commit not reused", code, out)
	}
	got := out["grant"].(map[string]any)
	if got["grant_id"] != draftID || got["created_at"] != "2026-09-11T01:00:00Z" {
		t.Fatal("retry did not return the committed draft", got)
	}
	if stateRevision(t, out) != 0 {
		t.Fatal("unexpected draft revision", out)
	}
}
