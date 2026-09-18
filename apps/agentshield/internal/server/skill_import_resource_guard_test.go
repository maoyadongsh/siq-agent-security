package server

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestImportedResourceEditsRecheckSourceWithoutMutation(t *testing.T) {
	for _, change := range []string{"missing", "changed"} {
		t.Run(change, func(t *testing.T) {
			s, id, request := importPermissionFixture(t)
			code, response := call(t, s, "POST", "/v1/skill-imports/"+id+"/permissions", token, request)
			if code != 201 {
				t.Fatal(code, response)
			}
			grantID := response["grant"].(map[string]any)["grant_id"].(string)
			before, revision, err := s.d.Store.GetGrantWithSeq(grantID)
			if err != nil {
				t.Fatal(err)
			}
			rawBefore, _ := json.Marshal(before)
			audit, err := s.d.Store.TailAudit(100)
			if err != nil {
				t.Fatal(err)
			}
			auditBefore, _ := json.Marshal(audit)
			payload := filepath.Join(s.d.Store.Dir, "skill-imports", "blobs", id, "payload", "SKILL.md")
			if change == "missing" {
				if err := os.Remove(payload); err != nil {
					t.Fatal(err)
				}
			} else if err := os.WriteFile(payload, []byte("changed imported bytes"), 0600); err != nil {
				t.Fatal(err)
			}
			body := map[string]any{"schema_version": "grant-resource-edit/v1", "expected_revision": revision, "actor_id": request.ActorID,
				"tools": []string{"read_file"}, "network": []any{}, "models": []string{}, "filesystem": map[string]any{"read_only": []string{"/work"}, "read_write": []string{}}}
			code, response = call(t, s, "POST", "/v1/grants/"+grantID+"/resources", token, body)
			if code != 409 || response["error"] != "skill_import_changed" {
				t.Fatal("changed import acquired edited permission", code, response)
			}
			after, nextRevision, err := s.d.Store.GetGrantWithSeq(grantID)
			if err != nil || nextRevision != revision {
				t.Fatal("failed edit advanced permission revision", err)
			}
			rawAfter, _ := json.Marshal(after)
			audit, err = s.d.Store.TailAudit(100)
			if err != nil {
				t.Fatal(err)
			}
			auditAfter, _ := json.Marshal(audit)
			if !bytes.Equal(rawBefore, rawAfter) || !bytes.Equal(auditBefore, auditAfter) {
				t.Fatal("failed import validation changed grant or audit")
			}
		})
	}
}

func TestImportedGrantSkillReferenceMustMatchSignedAdmission(t *testing.T) {
	s, id, request := importPermissionFixture(t)
	code, response := call(t, s, "POST", "/v1/skill-imports/"+id+"/permissions", token, request)
	if code != 201 {
		t.Fatal(code, response)
	}
	g, _, err := s.d.Store.GetGrantWithSeq(response["grant"].(map[string]any)["grant_id"].(string))
	if err != nil || g.Skill == nil {
		t.Fatal("missing import reference fixture", err)
	}
	if err := s.validateImportedGrant(context.Background(), *g); err != nil {
		t.Fatal(err)
	}
	for _, altered := range []string{"missing", "id", "hash", "version"} {
		t.Run(altered, func(t *testing.T) {
			candidate := *g
			skill := *g.Skill
			candidate.Skill = &skill
			switch altered {
			case "missing":
				candidate.Skill = nil
			case "id":
				candidate.Skill.SkillID += "-other"
			case "hash":
				candidate.Skill.ContentHash = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
			case "version":
				version := "another-version"
				candidate.Skill.Version = &version
			}
			// Produce a valid signature through the existing draft editor, so
			// refusal specifically proves the cross-document reference check.
			signed, _, err := grant.PatchDesired(candidate, grant.DesiredPatch{HasTools: true, Tools: []string{"read_file"}}, s.d.Key)
			if err != nil || !grant.Verify(s.d.Key.Public(), signed) {
				t.Fatal("invalid signed fixture", err)
			}
			if err := s.validateImportedGrant(context.Background(), signed); err == nil {
				t.Fatal("signed unrelated Skill reference accepted")
			}
		})
	}
}
