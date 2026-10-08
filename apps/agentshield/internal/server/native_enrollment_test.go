package server

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func nativeEnrollmentFixture(t *testing.T) (*nativeOnlineFixture, map[string]any, string) {
	t.Helper()
	f := nativeOnlineServer(t)
	old, err := f.server.runtimeIdentities.InspectByInstance(f.subject.InstanceID)
	if err != nil {
		t.Fatal(err)
	}
	_, revision, err := f.server.d.Store.GetGrantWithSeq(old.GrantRef.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.server.runtimeIdentities.Revoke(old.IdentityID, "fixture-migration"); err != nil {
		t.Fatal(err)
	}
	code, paired := call(t, f.server, "POST", "/v1/pair", "", map[string]any{"code": testPairingCode})
	if code != 200 {
		t.Fatal("fixture pairing failed", code)
	}
	return f, map[string]any{"schema_version": "local-runtime-identity-create/v3", "instance_id": old.InstanceID,
		"grant_id": old.GrantRef.GrantID, "expected_grant_revision": revision, "actor_id": "fixture-human", "session_ttl_seconds": 300,
		"native_skill_policy": map[string]any{"mode": "required", "runtime_artifact_sha256": strings.Repeat("c", 64)}}, paired["session"].(string)
}

func TestNativeEnrollmentHTTPDoesNotAuthorizeUnregisteredRuntime(t *testing.T) {
	f, request, admin := nativeEnrollmentFixture(t)
	code, issued := scopedCall(t, f.server, "/v1/runtime-identities", admin, request)
	if code != 201 || issued["schema_version"] != "local-runtime-identity-issued/v3" {
		t.Fatal("native identity issuance failed", code)
	}
	summary := issued["identity"].(map[string]any)
	if summary["runtime_state"] != "unverified" || summary["agent_id"] != f.subject.AgentID {
		t.Fatal("issuance claimed runtime verification or changed identity")
	}
	nativeReadbackSample(t, "local-runtime-identity-issued-native-v3", issued)
	credential, err := os.ReadFile(issued["credential_path"].(string))
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(issued)
	if strings.Contains(string(raw), string(credential)) || strings.Contains(string(raw), "credential_hash") {
		t.Fatal("issuance exposed credential")
	}
	code, enrolled := scopedCall(t, f.server, "/v1/runtime-sessions", string(credential), map[string]any{
		"schema_version": "local-runtime-session-enroll/v1", "session_id": "new-native-session"})
	if code != 200 || enrolled["schema_version"] != "local-runtime-session-enrolled/v3" || enrolled["runtime_state"] != "unverified" {
		t.Fatal("session claimed verified runtime", code)
	}
	body := map[string]any{"platform": "hermes", "agent_id": f.subject.AgentID, "session_id": "new-native-session",
		"runtime_task_id": "not-registered", "tool": "read_file", "tool_call_id": "no-proof", "params": map[string]any{"path": "/work/public/report"}}
	if code, _ := scopedCall(t, f.server, "/v1/decide", string(credential), body); code != 409 {
		t.Fatal("issued policy enabled execution without host registration", code)
	}
	if code, _ := scopedCall(t, f.server, "/v1/runtime-identities", admin, request); code != 409 {
		t.Fatal("new root silently replaced existing identity", code)
	}
	rows, err := f.server.d.Chain.Read()
	if err != nil || len(rows) != 0 {
		t.Fatal("unregistered runtime produced a decision receipt", err)
	}
}

func TestNativeEnrollmentRejectsNonManagementCredentials(t *testing.T) {
	f, request, _ := nativeEnrollmentFixture(t)
	for _, credential := range []string{"", token, f.credential, f.publisher} {
		code, _ := scopedCall(t, f.server, "/v1/runtime-identities", credential, request)
		if code != 401 && code != 403 {
			t.Fatal("non-management credential issued identity", code)
		}
	}
	nativeEnrollmentHasNoNewRecord(t, f)
}

func nativeEnrollmentHasNoNewRecord(t *testing.T, f *nativeOnlineFixture) {
	t.Helper()
	rows, err := f.server.runtimeIdentities.List()
	if err != nil || len(rows) != 1 || rows[0].Status != "revoked" {
		t.Fatal("failed issuance published an identity", err)
	}
}

func TestNativeEnrollmentRejectsIncompleteOrChangedWiring(t *testing.T) {
	for _, failure := range []string{"missing", "unbound", "changed-config", "missing-socket", "poisoned"} {
		t.Run(failure, func(t *testing.T) {
			f, request, admin := nativeEnrollmentFixture(t)
			switch failure {
			case "missing":
				f.server.d.NativeRuntime = nil
			case "unbound":
				f.server.d.NativeRuntime = &NativeRuntime{}
			case "changed-config":
				if err := os.WriteFile(f.native.configPath, []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			case "missing-socket":
				if err := os.Remove(f.native.connection.VerificationSocket); err != nil {
					t.Fatal(err)
				}
			case "poisoned":
				f.native.failed.Store(true)
			}
			if code, out := scopedCall(t, f.server, "/v1/runtime-identities", admin, request); code != 503 || out["error"] != "native_skill_runtime_unavailable" {
				t.Fatal("unavailable host accepted enrollment", code)
			}
			nativeEnrollmentHasNoNewRecord(t, f)
		})
	}
}

func TestNativeEnrollmentStrictVersionAndPolicyShape(t *testing.T) {
	f, request, admin := nativeEnrollmentFixture(t)
	encoded, _ := json.Marshal(request)
	raw := string(encoded)
	for name, body := range map[string]string{
		"extra":                  strings.Replace(raw, "{", `{"verified":true,`, 1),
		"duplicate":              strings.Replace(raw, "{", `{"actor_id":"other",`, 1),
		"null-policy":            strings.Replace(raw, `{"mode":"required","runtime_artifact_sha256":"`+strings.Repeat("c", 64)+`"}`, "null", 1),
		"wrong-version":          strings.Replace(raw, "local-runtime-identity-create/v3", "local-runtime-identity-create/v1", 1),
		"wrong-case":             strings.Replace(raw, "native_skill_policy", "Native_Skill_Policy", 1),
		"optional-policy":        strings.Replace(raw, `"required"`, `"optional"`, 1),
		"unknown-policy-field":   strings.Replace(raw, `"mode":"required"`, `"mode":"required","verified":true`, 1),
		"duplicate-policy-field": strings.Replace(raw, `"mode":"required"`, `"mode":"required","mode":"required"`, 1),
		"bad-artifact":           strings.Replace(raw, strings.Repeat("c", 64), strings.Repeat("C", 64), 1),
	} {
		t.Run(name, func(t *testing.T) {
			if code, _ := scopedCall(t, f.server, "/v1/runtime-identities", admin, body); code != 400 {
				t.Fatal("invalid native creation shape accepted", code)
			}
		})
	}
	nativeEnrollmentHasNoNewRecord(t, f)
}

func TestNativeEnrollmentPreservesApprovedGrantRevision(t *testing.T) {
	f, request, admin := nativeEnrollmentFixture(t)
	request["expected_grant_revision"] = request["expected_grant_revision"].(int) + 1
	if code, _ := scopedCall(t, f.server, "/v1/runtime-identities", admin, request); code != 409 {
		t.Fatal("stale grant selection accepted", code)
	}
	nativeEnrollmentHasNoNewRecord(t, f)
}
