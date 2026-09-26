package server

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func batchPreview(t *testing.T, s *Server, gid string, rev int) grantBatchPlan {
	t.Helper()
	code, out := call(t, s, "POST", "/v1/grant-batches/preview", token, map[string]any{
		"schema_version": "grant-batch-revoke-request/v1", "actor_id": "operator",
		"targets": []map[string]any{{"grant_id": gid, "expected_revision": rev}},
	})
	if code != 200 {
		t.Fatal(code, out)
	}
	raw, _ := json.Marshal(out)
	var plan grantBatchPlan
	if json.Unmarshal(raw, &plan) != nil {
		t.Fatal("invalid plan")
	}
	return plan
}
func batchApply(t *testing.T, s *Server, plan grantBatchPlan) (int, map[string]any) {
	t.Helper()
	return call(t, s, "POST", "/v1/grant-batches/apply", token, map[string]any{"schema_version": "grant-batch-revoke-apply/v1", "confirmed": true, "plan": plan})
}
func batchStatus(t *testing.T, out map[string]any, i int) string {
	t.Helper()
	return out["items"].([]any)[i].(map[string]any)["status"].(string)
}

func TestGrantBatchRevokePreviewAuditAndReplay(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	plan := batchPreview(t, s, gid, rev)
	before, seq, _ := store.GetGrantWithSeq(gid)
	if seq != rev || before.Status != "pending_approval" {
		t.Fatal("preview mutated authority")
	}
	if code, out := batchApply(t, s, plan); code != 200 || batchStatus(t, out, 0) != "revoked" {
		t.Fatal(code, out)
	}
	g, seq, _ := store.GetGrantWithSeq(gid)
	if seq != rev+1 || g.Status != "revoked" || !grant.Verify(s.d.Key.Public(), *g) {
		t.Fatal("bad revoked grant")
	}
	if code, out := batchApply(t, s, plan); code != 200 || batchStatus(t, out, 0) != "already_revoked" {
		t.Fatal(code, out)
	}
	_, seq, _ = store.GetGrantWithSeq(gid)
	if seq != rev+1 {
		t.Fatal("replay wrote another version")
	}
	events, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, ev := range events {
		if ev.Event == "grant_revoke" {
			count++
			if ev.Note != "batch="+plan.BatchID || ev.Target != gid || ev.ActorID != "operator" {
				t.Fatal(ev)
			}
		}
	}
	if count != 1 {
		t.Fatal("must have exactly one audited revocation", count)
	}
}

func TestGrantBatchRejectsTamperExpiryDecisionCredentialAndMalformed(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	original := batchPreview(t, s, gid, rev)
	for _, route := range []string{"preview", "apply"} {
		req := loopbackRequest("POST", "/v1/grant-batches/"+route, map[string]any{})
		req.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, req)
		if w.Code != 403 {
			t.Fatal("decision credential authorized management", w.Code)
		}
	}
	for _, mutate := range []func(*grantBatchPlan){
		func(p *grantBatchPlan) { p.ActorID = "other" },
		func(p *grantBatchPlan) { p.Action = "approve" },
		func(p *grantBatchPlan) { p.Items[0].ExpectedRevision++ },
		func(p *grantBatchPlan) { p.Items[0].GrantID = "another" },
		func(p *grantBatchPlan) {
			p.ExpiresAt = time.Now().Add(-time.Minute).Format(time.RFC3339Nano)
			p.Signature, _ = s.d.Key.SignCanonical(p.document())
		},
		func(p *grantBatchPlan) {
			p.Items = append(p.Items, p.Items[0])
			p.Signature, _ = s.d.Key.SignCanonical(p.document())
		},
	} {
		p := original
		p.Items = append([]grantBatchItem(nil), original.Items...)
		mutate(&p)
		if code, out := batchApply(t, s, p); code != 400 {
			t.Fatal(code, out)
		}
	}
	for _, targets := range []any{nil, []any{}, []any{map[string]any{"grant_id": gid}},
		[]any{map[string]any{"grant_id": gid, "expected_revision": rev}, map[string]any{"grant_id": gid, "expected_revision": rev}},
		[]any{map[string]any{"grant_id": gid, "expected_revision": -1}},
	} {
		if code, out := call(t, s, "POST", "/v1/grant-batches/preview", token, map[string]any{"schema_version": "grant-batch-revoke-request/v1", "actor_id": "operator", "targets": targets}); code != 400 {
			t.Fatal(code, out)
		}
	}
	if code, _ := call(t, s, "POST", "/v1/grant-batches/apply", token, map[string]any{"schema_version": "grant-batch-revoke-apply/v1", "confirmed": false, "plan": original}); code != 400 {
		t.Fatal(code)
	}
	_, seq, _ := store.GetGrantWithSeq(gid)
	if seq != rev {
		t.Fatal("invalid request changed grant")
	}
}

func TestGrantBatchPartialConflictAndAuditFailure(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	p := batchPreview(t, s, gid, rev)
	// Independently change the selected grant before apply.
	call(t, s, "POST", "/v1/grants/"+gid+"/expiry", token, map[string]any{"schema_version": "grant-expiry-edit/v1", "expected_revision": rev, "actor_id": "operator", "duration_seconds": 60})
	code, out := batchApply(t, s, p)
	if code != 200 || batchStatus(t, out, 0) != "conflict" {
		t.Fatal(code, out)
	}
	_, seq, _ := store.GetGrantWithSeq(gid)
	p = batchPreview(t, s, gid, seq)
	if err := os.MkdirAll(filepath.Join(store.Dir, "commit-audit", fmt.Sprintf("%s.%d.json", gid, seq+1)), 0700); err != nil {
		t.Fatal(err)
	}
	code, out = batchApply(t, s, p)
	if code != 200 || batchStatus(t, out, 0) != "unavailable" {
		t.Fatal(code, out)
	}
	if _, _, err := store.GetGrantWithSeq(gid); err == nil {
		t.Fatal("unaudited commit exposed")
	}
	code, out = batchApply(t, s, p)
	if code != 200 || batchStatus(t, out, 0) != "unavailable" {
		t.Fatal("unknown became successful", code, out)
	}
}

func TestGrantBatchStrictJSON(t *testing.T) {
	s, _, gid, rev := expiryFixture(t)
	for _, raw := range []string{
		fmt.Sprintf(`{"schema_version":"grant-batch-revoke-request/v1","actor_id":"operator","targets":[{"grant_id":%q,"grant_id":%q,"expected_revision":%d}]}`, gid, gid, rev),
		`{"schema_version":"grant-batch-revoke-request/v1","actor_id":"operator","targets":[]} {}`,
	} {
		session, err := s.RedeemPairing(testPairingCode)
		if err != nil { // The helper's same admin session can be reused after the first request.
			s.sessMu.Lock()
			for existing := range s.sessions {
				session = existing
				break
			}
			s.sessMu.Unlock()
		}
		req := loopbackRequest("POST", "/v1/grant-batches/preview", nil)
		req.Body = io.NopCloser(strings.NewReader(raw))
		req.Header.Set("Authorization", "Bearer "+session)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, req)
		if w.Code != 400 {
			t.Fatal(w.Code, w.Body.String())
		}
	}
}

func TestGrantBatchPartialSuccess(t *testing.T) {
	s, store, first, rev := expiryFixture(t)
	g, _, _ := store.GetGrantWithSeq(first)
	code, created := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": g.AdmissionID, "platform": "hermes", "subject_id": "second-role"})
	if code != 200 {
		t.Fatal(created)
	}
	second := created["grant"].(map[string]any)["grant_id"].(string)
	secondRev := stateRevision(t, created)
	code, preview := call(t, s, "POST", "/v1/grant-batches/preview", token, map[string]any{
		"schema_version": "grant-batch-revoke-request/v1", "actor_id": "operator",
		"targets": []any{map[string]any{"grant_id": first, "expected_revision": rev}, map[string]any{"grant_id": second, "expected_revision": secondRev}},
	})
	if code != 200 {
		t.Fatal(preview)
	}
	var plan grantBatchPlan
	raw, _ := json.Marshal(preview)
	if json.Unmarshal(raw, &plan) != nil {
		t.Fatal("invalid plan")
	}
	code, changed := call(t, s, "POST", "/v1/grants/"+first+"/expiry", token, map[string]any{"schema_version": "grant-expiry-edit/v1", "expected_revision": rev, "actor_id": "operator", "duration_seconds": 60})
	if code != 200 {
		t.Fatal(changed)
	}
	code, out := batchApply(t, s, plan)
	if code != 200 || batchStatus(t, out, 0) != "conflict" || batchStatus(t, out, 1) != "revoked" {
		t.Fatal(code, out)
	}
	firstGrant, _, _ := store.GetGrantWithSeq(first)
	secondGrant, _, _ := store.GetGrantWithSeq(second)
	if firstGrant.Status != "pending_approval" || secondGrant.Status != "revoked" {
		t.Fatal("partial result mismatch")
	}
}

func TestGrantBatchRequestContractFixture(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/grant-batch-revoke.json")
	if err != nil {
		t.Fatal(err)
	}
	var request map[string]any
	if json.Unmarshal(raw, &request) != nil {
		t.Fatal("bad fixture")
	}
	s, _, gid, rev := expiryFixture(t)
	item := request["targets"].([]any)[0].(map[string]any)
	item["grant_id"], item["expected_revision"] = gid, rev
	if code, out := call(t, s, "POST", "/v1/grant-batches/preview", token, request); code != 200 {
		t.Fatal(code, out)
	}
}

func TestGrantBatchStrictPlanRejectsNullMissingAndCaseAliases(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	p := batchPreview(t, s, gid, rev)
	raw, _ := json.Marshal(p)
	for _, kind := range []string{"null_revision", "missing_revision", "case_revision", "missing_signature"} {
		var body map[string]any
		if json.Unmarshal(raw, &body) != nil {
			t.Fatal("fixture")
		}
		item := body["items"].([]any)[0].(map[string]any)
		switch kind {
		case "null_revision":
			item["expected_revision"] = nil
		case "missing_revision":
			delete(item, "expected_revision")
		case "case_revision":
			delete(item, "expected_revision")
			item["EXPECTED_REVISION"] = rev
		case "missing_signature":
			delete(body, "signature")
		}
		code, out := call(t, s, "POST", "/v1/grant-batches/apply", token, map[string]any{"schema_version": "grant-batch-revoke-apply/v1", "confirmed": true, "plan": body})
		if code != 400 {
			t.Fatal(kind, code, out)
		}
	}
	_, seq, _ := store.GetGrantWithSeq(gid)
	if seq != rev {
		t.Fatal("malformed plan changed authority")
	}
}
