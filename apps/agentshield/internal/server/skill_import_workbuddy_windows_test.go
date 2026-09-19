package server

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/skillcontext"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

// Real managed state and HTTP authority chain, with synthetic nonexecuted
// Skill content. No WorkBuddy process, desktop, provider or model is started.
func TestWorkBuddyImportedSkillPermissionAndTargetPlanV2(t *testing.T) {
	workBuddyImportedPlanFixture(t)
}

func workBuddyImportedPlanFixture(t *testing.T) (windowsAuthorityHTTPFixture, skillinstall.Plan, string) {
	t.Helper()
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
	return f, typed, create.ActorID
}

func TestWorkBuddyInstalledSessionManagementRoundTrip(t *testing.T) {
	f, plan, actor := workBuddyImportedPlanFixture(t)
	contexts, err := skillcontext.Open(f.st.Dir, skillcontext.Deps{
		Key: f.s.d.Key,
		ReadGrant: func(id string) (*grant.Grant, error) {
			g := f.st.GrantByID(id)
			if g == nil {
				return nil, os.ErrNotExist
			}
			return g, nil
		},
		// The previous CLI-only reader must be replaced by the daemon's v2 reader.
		ReadInstall:  func(string) (*skillinstall.Record, error) { return nil, errors.New("legacy reader must not be used") },
		ReadInstance: f.s.runtimeIdentities.InspectByInstance,
		SessionBound: func(platform, agent, session, grantID string) (time.Time, error) {
			_, b, err := f.s.intents.ResolveBinding(platform, session, agent)
			if err != nil || b == nil || b.GrantRef == nil || b.GrantRef.GrantID != grantID {
				return time.Time{}, os.ErrNotExist
			}
			return time.Parse(time.RFC3339, b.ExpiresAt)
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := contexts.BindInstallationStore(f.s.skillInstallations); err != nil {
		t.Fatal(err)
	}
	f.s.skillContexts = contexts
	out := windowsAuthorityHTTP(t, f.s, "POST", "/v1/skill-installations/apply", f.s.bootAdmin,
		skillinstall.ApplyRequest{SchemaVersion: "local-skill-install-apply/v1", PlanID: plan.PlanID, PlanSignature: plan.Signature, ActorID: actor, ConfirmInstall: true}, 200)
	id := out["install_id"].(string)
	op := out["operation"].(map[string]any)
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/skill-installations/operations/"+id+"/activate", f.s.bootAdmin,
		skillinstall.ActivateRequest{SchemaVersion: "local-skill-install-activate/v1", OperationSignature: op["signature"].(string), ExpectedRevision: plan.GrantRevision, ActorID: actor, ConfirmInstanceScope: true}, 200)
	// An existing identity pinned to another Grant must not expose its sessions.
	route := "/v1/skill-contexts/management?install_id=" + id
	before := windowsAuthorityHTTP(t, f.s, "GET", route, f.s.bootAdmin, nil, 200)
	if len(before["sessions"].([]any)) != 0 {
		t.Fatal("foreign Grant session offered")
	}
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-identities/"+f.identityID+"/revoke", f.s.bootAdmin,
		map[string]any{"schema_version": "local-runtime-identity-revoke/v1", "actor_id": actor}, 200)
	issued := windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-identities", f.s.bootAdmin,
		map[string]any{"schema_version": "local-runtime-identity-create/v2", "confirm_filesystem_profile": true, "instance_id": f.instance, "grant_id": plan.GrantID, "expected_grant_revision": plan.GrantRevision + 1, "actor_id": actor, "session_ttl_seconds": 3600}, 201)
	credential, err := os.ReadFile(issued["credential_path"].(string))
	if err != nil {
		t.Fatal(err)
	}
	session := "workbuddy-session/v1:" + strings.Repeat("e", 64)
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-sessions", string(credential), map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": session}, 200)
	before = windowsAuthorityHTTP(t, f.s, "GET", route, f.s.bootAdmin, nil, 200)
	if len(before["sessions"].([]any)) != 1 || before["sessions"].([]any)[0].(map[string]any)["session_id"] != session {
		t.Fatal("registered session missing", before)
	}
	request := map[string]any{"schema_version": "local-skill-execution-context-issue/v1", "instance_id": f.instance, "install_id": id, "session_id": session, "task_id": "", "actor_id": actor, "ttl_seconds": 600, "confirm_issue": true}
	context := windowsAuthorityHTTP(t, f.s, "POST", "/v1/skill-contexts", f.s.bootAdmin, request, 201)
	verified, verifyErr := contexts.Verify("workbuddy", f.agent, session, "")
	if verifyErr != nil || verified == nil || verified.Invalid || verified.Context.ContextID != context["context_id"] {
		t.Fatal("issued SEC did not pass runtime revalidation", verifyErr)
	}
	readback := windowsAuthorityHTTP(t, f.s, "GET", route, f.s.bootAdmin, nil, 200)
	rows := readback["contexts"].([]any)
	if len(rows) != 1 || rows[0].(map[string]any)["revoked"] != false || rows[0].(map[string]any)["context"].(map[string]any)["signature"] != context["signature"] {
		t.Fatal("lost issue response not recoverable")
	}
	workBuddyContractSample(t, "local-skill-context-management.v1", readback)
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/skill-contexts", f.s.bootAdmin, request, 409)
	revoke := "/v1/skill-contexts/" + context["context_id"].(string) + "/revoke"
	windowsAuthorityHTTP(t, f.s, "POST", revoke, f.s.bootAdmin, map[string]any{"schema_version": "local-skill-execution-context-revoke/v1", "expected_context_signature": strings.Repeat("0", 128), "actor_id": actor, "confirm_revoke": true}, 409)
	windowsAuthorityHTTP(t, f.s, "POST", revoke, f.s.bootAdmin, map[string]any{"schema_version": "local-skill-execution-context-revoke/v1", "expected_context_signature": context["signature"], "actor_id": actor, "confirm_revoke": true}, 200)
	readback = windowsAuthorityHTTP(t, f.s, "GET", route, f.s.bootAdmin, nil, 200)
	if readback["contexts"].([]any)[0].(map[string]any)["revoked"] != true {
		t.Fatal("revocation not read back")
	}
	verified, verifyErr = contexts.Verify("workbuddy", f.agent, session, "")
	if verifyErr != nil || verified == nil || !verified.Invalid {
		t.Fatal("revoked SEC remained usable", verifyErr)
	}
}
