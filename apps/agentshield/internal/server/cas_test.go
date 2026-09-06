package server

import (
	"path/filepath"
	"testing"
)

func TestGrantActionRequiresExpectedRevisionAndConflicts(t *testing.T) {
	s, _ := newServer(t, "block")
	skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc"))
	_, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
	admID := a["admission"].(map[string]any)["admission_id"].(string)
	code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "cas"})
	if code != 200 {
		t.Fatalf("create: %d %v", code, g)
	}
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	rev := stateRevision(t, g)

	code, one := approveChallenged(t, s, gid, "a", rev)
	if code != 200 {
		t.Fatalf("approve: %d %v", code, one)
	}
	// Stale revision on challenge (grant moved to rev+1) must conflict.
	code, stale := call(t, s, "POST", "/v1/grants/"+gid+"/challenge", token, withRevision(nil, rev))
	if code != 409 {
		t.Fatalf("stale expected must 409: %d %v", code, stale)
	}
	code, got := call(t, s, "GET", "/v1/grants/"+gid, token, nil)
	if code != 200 || stateRevision(t, got) != stateRevision(t, one) {
		t.Fatalf("get: %d %v", code, got)
	}
	if got["grant"].(map[string]any)["status"] != "approved" {
		t.Fatalf("status: %v", got)
	}
}
