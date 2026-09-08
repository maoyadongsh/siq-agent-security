package server

import (
	"encoding/json"
	"net/http/httptest"
	"path/filepath"
	"testing"
)

func TestToolApprovalHTTPRequiresAdminAndAuditedPendingMutation(t *testing.T) {
	s, store := newServer(t, "block")
	path, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))
	_, admitted := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": path})
	_, created := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admitted["admission"].(map[string]any)["admission_id"], "platform": "hermes", "subject_id": "approval-agent"})
	gid := created["grant"].(map[string]any)["grant_id"].(string)
	route := "/v1/grants/" + gid
	_, patched := call(t, s, "POST", route+"/patch-desired", token, withRevision(map[string]any{"tools": []string{"read_file"}}, stateRevision(t, created)))
	revision := stateRevision(t, patched)
	body := map[string]any{"schema_version": "grant-tool-approval/v1", "expected_revision": revision, "actor_id": "operator", "tools": []string{"read_file"}}
	post := func(bearer string, input any, expected int) map[string]any {
		t.Helper()
		req := loopbackRequest("POST", route+"/require-approval", input)
		req.Header.Set("Authorization", "Bearer "+bearer)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, req)
		if w.Code != expected {
			t.Fatalf("HTTP %d want %d: %s", w.Code, expected, w.Body.String())
		}
		var value map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &value); err != nil {
			t.Fatal(err)
		}
		return value
	}
	post(token, body, 403)
	body["unknown"] = true
	post(s.bootAdmin, body, 400)
	delete(body, "unknown")
	body["tools"] = []string{"ungranted"}
	post(s.bootAdmin, body, 400)
	_, seq, _ := store.GetGrantWithSeq(gid)
	if seq != revision {
		t.Fatal("failed request mutated authority")
	}
	body["tools"] = []string{"read_file"}
	post(s.bootAdmin, body, 200)
	post(s.bootAdmin, body, 409)
	audit, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, event := range audit {
		if event.Event == "grant_require_approval" && event.Target == gid && event.ActorID == "operator" {
			found = true
		}
	}
	if !found {
		t.Fatal("approval condition lacks audit")
	}
}
