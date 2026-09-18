package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

// Real managed state and HTTP authority chain, with synthetic nonexecuted
// Skill content. No WorkBuddy process, desktop, provider or model is started.
func TestWorkBuddyImportedSkillPermissionAndTargetPlanV2(t *testing.T) {
	f := newWindowsAuthorityHTTPFixtureForPlatform(t, "block", false, "workbuddy")
	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("---\nname: scoped-import\ndescription: Read a fixture.\n---\nRead a synthetic report.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	create := skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: "si-" + strings.Repeat("a", 32), SourceKind: "local_dir", Path: source, ActorID: "fixture-human"}
	imported := windowsAuthorityHTTP(t, f.s, "POST", "/v1/skill-imports", f.s.bootAdmin, create, 201)["import"].(map[string]any)
	permission := importPermissionRequest{SchemaVersion: "local-skill-import-permission-create/v1", RequestID: "ip-" + strings.Repeat("b", 32),
		ArtifactDigest: imported["artifact_digest"].(string), AnalysisSHA256: imported["analysis_sha256"].(string), InstanceID: f.instance, ActorID: create.ActorID}
	route := "/v1/skill-imports/" + create.ImportID + "/permissions"
	drafted := windowsAuthorityHTTP(t, f.s, "POST", route, f.s.bootAdmin, permission, 201)
	g := drafted["grant"].(map[string]any)
	if drafted["schema_version"] != "local-skill-import-permission-created/v1" || g["platform"] != "workbuddy" || g["skill"] == nil {
		t.Fatal("import source or initial version lost", drafted)
	}
	grantID := g["grant_id"].(string)
	resource := map[string]any{"schema_version": "grant-resource-edit/v2", "expected_revision": drafted["state_revision"], "actor_id": create.ActorID,
		"confirm_filesystem_profile": true, "tools": []string{"read_file"}, "network": []any{}, "models": []string{},
		"filesystem": map[string]any{"read_only": []string{f.root}, "read_write": []string{}}}
	edited := windowsAuthorityHTTP(t, f.s, "POST", "/v1/grants/"+grantID+"/resources", f.s.bootAdmin, resource, 200)
	updated := edited["grant"].(map[string]any)
	if updated["schema_version"] != "grant/v2" || !reflect.DeepEqual(updated["skill"], g["skill"]) || updated["admission_id"] != g["admission_id"] || updated["status"] != "pending_approval" {
		t.Fatal("Windows edit replaced imported provenance or approved implicitly")
	}
	reused := windowsAuthorityHTTP(t, f.s, "POST", route, f.s.bootAdmin, permission, 200)
	if reused["schema_version"] != "local-skill-import-permission-created/v2" || reused["reused"] != true || !reflect.DeepEqual(reused["grant"], edited["grant"]) {
		t.Fatal("v2 grant returned in legacy permission wrapper", reused)
	}
	challenge := windowsAuthorityHTTP(t, f.s, "POST", "/v1/grants/"+grantID+"/challenge", f.s.bootAdmin,
		map[string]any{"expected_revision": edited["state_revision"], "actor_id": create.ActorID}, 200)["challenge"].(map[string]any)
	approved := windowsAuthorityHTTP(t, f.s, "POST", "/v1/grants/"+grantID+"/approve", f.s.bootAdmin,
		map[string]any{"expected_revision": edited["state_revision"], "actor_id": create.ActorID, "challenge_id": challenge["challenge_id"], "nonce": challenge["nonce"]}, 200)
	listed := windowsAuthorityHTTP(t, f.s, "GET", "/v1/skill-installation-targets?instance_id="+f.instance, f.s.bootAdmin, nil, 200)
	target := listed["targets"].([]any)[0].(map[string]any)
	request := skillinstall.Request{SchemaVersion: "local-skill-install-stage-create/v2", TargetID: target["target_id"].(string), RequestID: "is-" + strings.Repeat("c", 32),
		GrantID: grantID, ExpectedRevision: int(approved["state_revision"].(float64)), InstanceID: f.instance, DirectoryName: "scoped-import", ActorID: create.ActorID}
	plan := windowsAuthorityHTTP(t, f.s, "POST", "/v1/skill-installations/plans", f.s.bootAdmin, request, 201)
	if plan["schema_version"] != "local-skill-install-plan-created/v2" {
		t.Fatal("new plan in old wrapper", plan)
	}
	var typed skillinstall.Plan
	raw, _ := json.Marshal(plan["plan"])
	if json.Unmarshal(raw, &typed) != nil || typed.TargetRef == nil || typed.TargetRef.TargetID != request.TargetID || typed.InstanceID != f.instance || typed.Platform != "workbuddy" {
		t.Fatal("stage lost selected target identity")
	}
	root, _, err := f.s.workBuddyRoot()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(filepath.Join(root, "skills", request.DirectoryName)); !os.IsNotExist(err) {
		t.Fatal("preview installed without separate apply", err)
	}
}
