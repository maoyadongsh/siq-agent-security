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

func TestRejectedApprovalDoesNotCommitOrConsumeChallenge(t *testing.T) {
	for _, scenario := range []string{"missing-actor", "unresolved-overlap"} {
		t.Run(scenario, func(t *testing.T) {
			s, _ := newServer(t, "block")
			skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "pure-doc"))
			code, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
			if code != 200 {
				t.Fatalf("admit: %d", code)
			}
			code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{
				"admission_id": a["admission"].(map[string]any)["admission_id"],
				"platform":     "hermes", "subject_id": "rejected-approval",
			})
			if code != 200 {
				t.Fatalf("grant: %d", code)
			}
			gid := g["grant"].(map[string]any)["grant_id"].(string)
			rev := stateRevision(t, g)
			actor := ""
			if scenario == "unresolved-overlap" {
				actor = "fixture-operator"
				code, patched := call(t, s, "POST", "/v1/grants/"+gid+"/patch-desired", token, withRevision(map[string]any{
					"filesystem": map[string]any{"read_only": []string{"/fixture"}, "read_write": []string{"/fixture"}},
				}, rev))
				if code != 200 {
					t.Fatalf("patch: %d", code)
				}
				rev = stateRevision(t, patched)
			}
			code, chResp := call(t, s, "POST", "/v1/grants/"+gid+"/challenge", token, withRevision(nil, rev))
			if code != 200 {
				t.Fatalf("challenge: %d", code)
			}
			ch := chResp["challenge"].(map[string]any)
			before, err := s.d.Store.TailAudit(100)
			if err != nil {
				t.Fatal(err)
			}
			body := withRevision(map[string]any{"actor_id": actor, "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]}, rev)
			code, rejected := call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, body)
			if code != 400 {
				t.Fatalf("invalid approval must return 400: %d %v", code, rejected)
			}
			stored, seq, err := s.d.Store.GetGrantWithSeq(gid)
			if err != nil || seq != rev || stored.Status != "pending_approval" || stored.ApprovedBy != nil {
				t.Fatalf("rejected approval changed grant: seq=%d err=%v", seq, err)
			}
			challenge, _, err := s.d.Store.GetChallengeWithSeq(ch["challenge_id"].(string))
			if err != nil || challenge.ConsumedAt != nil {
				t.Fatalf("invalid approval consumed challenge: %v", err)
			}
			after, err := s.d.Store.TailAudit(100)
			if err != nil || len(after) != len(before) {
				t.Fatalf("rejected approval appended success audit: %v", err)
			}
			if scenario == "missing-actor" {
				body["actor_id"] = "fixture-operator"
				code, accepted := call(t, s, "POST", "/v1/grants/"+gid+"/approve", token, body)
				if code != 200 || accepted["grant"].(map[string]any)["status"] != "approved" {
					t.Fatalf("corrected approval must succeed: %d %v", code, accepted)
				}
			}
		})
	}
}
