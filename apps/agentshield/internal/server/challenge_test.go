package server

import (
	"fmt"
	"path/filepath"
	"strings"
	"testing"
)

func TestApprovalChallengeReplayAndBodyChange(t *testing.T) {
	s, _ := newServer(t, "block")
	skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc"))
	code, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
	if code != 200 {
		t.Fatalf("admit: %d %v", code, a)
	}
	admID := a["admission"].(map[string]any)["admission_id"].(string)
	code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "chal"})
	if code != 200 {
		t.Fatalf("grant: %d %v", code, g)
	}
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	rev := stateRevision(t, g)

	code, chResp := call(t, s, "POST", "/v1/grants/"+gid+"/challenge", token, withRevision(nil, rev))
	if code != 200 {
		t.Fatalf("challenge: %d %v", code, chResp)
	}
	ch := chResp["challenge"].(map[string]any)
	body := withRevision(map[string]any{
		"actor_id": "human-1", "challenge_id": ch["challenge_id"], "nonce": ch["nonce"],
	}, rev)

	code, ok := call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, body)
	if code != 200 {
		t.Fatalf("first approve: %d %v", code, ok)
	}
	rev2 := stateRevision(t, ok)
	body2 := withRevision(map[string]any{
		"actor_id": "human-1", "challenge_id": ch["challenge_id"], "nonce": ch["nonce"],
	}, rev2)
	code, again := call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, body2)
	if code == 200 {
		t.Fatalf("replay must fail: %v", again)
	}
	errText := fmt.Sprint(again["error"])
	if !strings.Contains(errText, "consumed") && !strings.Contains(errText, "cannot approve") && !strings.Contains(errText, "challenge") {
		t.Fatalf("expected consumed/status/challenge error, got %v", again)
	}
}

func TestApprovalChallengeInvalidatedByPatch(t *testing.T) {
	s, _ := newServer(t, "block")
	skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc"))
	code, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
	if code != 200 {
		t.Fatalf("admit: %d %v", code, a)
	}
	admID := a["admission"].(map[string]any)["admission_id"].(string)
	code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": admID, "platform": "hermes", "subject_id": "patch-chal"})
	if code != 200 {
		t.Fatalf("grant: %d %v", code, g)
	}
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	rev := stateRevision(t, g)

	code, chResp := call(t, s, "POST", "/v1/grants/"+gid+"/challenge", token, withRevision(nil, rev))
	if code != 200 {
		t.Fatalf("challenge: %d %v", code, chResp)
	}
	ch := chResp["challenge"].(map[string]any)

	code, patched := call(t, s, "POST", "/v1/grants/"+gid+"/patch-desired", token, withRevision(map[string]any{
		"tools": []string{"read_file", "evil_tool"},
	}, rev))
	if code != 200 {
		t.Fatalf("patch: %d %v", code, patched)
	}
	rev2 := stateRevision(t, patched)

	code, bad := call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, withRevision(map[string]any{
		"actor_id": "h", "challenge_id": ch["challenge_id"], "nonce": ch["nonce"],
	}, rev2))
	if code == 200 {
		t.Fatalf("stale challenge after patch must fail: %v", bad)
	}
}
