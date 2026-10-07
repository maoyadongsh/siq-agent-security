package server

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

func TestNativeIdentityReadbacksAndRequestLifecycle(t *testing.T) {
	s, st := grantBindingServer(t, "block")
	rows := instanceFixture(t, s)
	instance := rows[1].(map[string]any)["instance_id"].(string)
	agent, _ := runtimeidentity.AgentID(instance)
	g, revision := selectedGrantFixture(t, s, st, "c", "/work/public", false, agent)
	req := runtimeidentity.CreateRequest{SchemaVersion: "local-runtime-identity-create/v1", InstanceID: instance, GrantID: g.GrantID, ExpectedGrantRevision: revision, ActorID: "fixture-human", SessionTTLSeconds: 300}
	old, err := s.runtimeIdentities.Create(req)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.runtimeIdentities.Revoke(old.IdentityID, "fixture-human"); err != nil {
		t.Fatal(err)
	}
	req.SchemaVersion = "local-runtime-identity-create/v3"
	req.NativeSkillPolicy = &runtimeidentity.NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: strings.Repeat("c", 64)}
	root, err := s.runtimeIdentities.Create(req)
	if err != nil {
		t.Fatal(err)
	}
	credential := nativeReadbackCredential(t, s, root.IdentityID)
	assertPolicy := func(value map[string]any) {
		t.Helper()
		if value["runtime_state"] != "unverified" || !reflect.DeepEqual(value["native_skill_policy"], map[string]any{"mode": "required", "runtime_artifact_sha256": strings.Repeat("c", 64)}) {
			t.Fatal("readback lost policy or claimed runtime verification", value)
		}
	}
	code, self := selfCall(t, s, "GET", "/v1/runtime-identity/self", credential, nil)
	if code != 200 || self["schema_version"] != "local-runtime-identity-self/v2" {
		t.Fatal("native self", code, self)
	}
	assertPolicy(self)
	nativeReadbackSample(t, "local-runtime-identity-self-native-v2", self)
	code, listed := call(t, s, "GET", "/v1/runtime-identities", token, nil)
	if code != 200 || listed["schema_version"] != "local-runtime-identities/v3" || len(listed["items"].([]any)) != 2 {
		t.Fatal("mixed identity list", code, listed)
	}
	for _, row := range listed["items"].([]any) {
		item := row.(map[string]any)
		if item["identity_id"] == root.IdentityID {
			assertPolicy(item)
		} else if _, exists := item["native_skill_policy"]; exists {
			t.Fatal("legacy summary gained native policy")
		}
	}
	// Persist a deterministic native-only projection of the actual HTTP list;
	// mixed ordering/platform version selection is checked separately below.
	for _, row := range listed["items"].([]any) {
		if row.(map[string]any)["identity_id"] == root.IdentityID {
			nativeReadbackSample(t, "local-runtime-identities-native-v3", map[string]any{"schema_version": listed["schema_version"], "items": []any{row}})
		}
	}
	code, enrolled := scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "native-session"})
	if code != 200 || enrolled["schema_version"] != "local-runtime-session-enrolled/v3" {
		t.Fatal("native session", code, enrolled)
	}
	assertPolicy(enrolled)
	nativeReadbackSample(t, "local-runtime-session-enrolled-native-v3", enrolled)
	// New root creation over HTTP remains closed. Validate the production
	// response projector without pretending this is an enabled HTTP enrollment.
	summary, err := s.runtimeIdentities.Summary(root.IdentityID)
	if err != nil {
		t.Fatal(err)
	}
	nativeReadbackSample(t, "local-runtime-identity-issued-native-v3", runtimeIdentityIssued(root, summary, "/synthetic/credential.token"))
	cap := map[string]any{"schema_version": "local-runtime-request-issuer-create/v1", "parent_identity_id": root.IdentityID, "scope_id": strings.Repeat("a", 24), "max_identity_seconds": 300, "expires_at": time.Now().UTC().Add(time.Hour).Format(time.RFC3339), "actor_id": "fixture-human"}
	if code, _ := call(t, s, "POST", "/v1/runtime-request-issuers", token, cap); code != 201 {
		t.Fatal("issuer", code)
	}
	request := map[string]any{"schema_version": "local-runtime-request-identity-create/v1", "request_id": "qwen-request-2222222222222222", "execution_sha256": strings.Repeat("d", 64), "expires_at": time.Now().UTC().Add(240 * time.Second).Format(time.RFC3339)}
	code, issued := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests", credential, request)
	if code != 201 || issued["schema_version"] != "local-runtime-request-identity-issued/v2" {
		t.Fatal("native child issuance", code, issued)
	}
	assertPolicy(issued["identity"].(map[string]any))
	nativeReadbackSample(t, "local-runtime-request-identity-issued-native-v2", issued)
	if code, retry := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests", credential, request); code != 201 || !reflect.DeepEqual(issued, retry) {
		t.Fatal("native child retry changed metadata", code)
	}
	childID := issued["identity"].(map[string]any)["identity_id"].(string)
	child := nativeReadbackCredential(t, s, childID)
	code, childSelf := selfCall(t, s, "GET", "/v1/runtime-identity/self", child, nil)
	if code != 200 || childSelf["schema_version"] != "local-runtime-identity-self/v2" {
		t.Fatal("child self", code)
	}
	assertPolicy(childSelf)
	scope := issued["request"].(map[string]any)
	session := scope["session_namespace"].(string) + ":" + strings.Repeat("b", 64)
	code, childSession := scopedCall(t, s, "/v1/runtime-sessions", child, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": session})
	if code != 200 || childSession["schema_version"] != "local-runtime-session-enrolled/v3" {
		t.Fatal("child enrollment", code)
	}
	assertPolicy(childSession)
	for _, value := range []any{self, listed, enrolled, issued, childSelf, childSession} {
		raw, _ := json.Marshal(value)
		for _, secret := range []string{credential, child, "credential_hash", "signature"} {
			if bytes.Contains(raw, []byte(secret)) {
				t.Fatal("private data in native readback")
			}
		}
	}
	cancel := map[string]any{"schema_version": "local-runtime-request-identity-cancel/v1", "request_id": request["request_id"], "execution_sha256": request["execution_sha256"]}
	if code, _ := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests/cancel", credential, cancel); code != 200 {
		t.Fatal("child cancellation", code)
	}
	if code, _ := selfCall(t, s, "GET", "/v1/runtime-identity/self", child, nil); code != 401 {
		t.Fatal("cancelled child exposed active metadata", code)
	}
	if _, err := s.runtimeIdentities.Revoke(root.IdentityID, "fixture-human"); err != nil {
		t.Fatal(err)
	}
	if code, _ := selfCall(t, s, "GET", "/v1/runtime-identity/self", credential, nil); code != 401 {
		t.Fatal("revoked root active", code)
	}
	_, listed = call(t, s, "GET", "/v1/runtime-identities", token, nil)
	if listed["schema_version"] != "local-runtime-identities/v3" {
		t.Fatal("revocation hid native policy")
	}
}

func nativeReadbackCredential(t *testing.T, s *Server, id string) string {
	t.Helper()
	path, err := s.runtimeIdentities.CredentialPath(id)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func nativeReadbackSample(t *testing.T, name string, value any) {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	var parsed any
	if json.Unmarshal(raw, &parsed) != nil {
		t.Fatal("invalid readback")
	}
	childResponse := parsed.(map[string]any)["schema_version"] == "local-runtime-request-identity-issued/v2"
	// Only volatile values are normalized, never version/shape/policy/status.
	var normalize func(any)
	normalize = func(v any) {
		switch v := v.(type) {
		case []any:
			for _, child := range v {
				normalize(child)
			}
		case map[string]any:
			for key, child := range v {
				switch key {
				case "identity_id":
					v[key] = "ri-" + strings.Repeat("3", 32)
					if childResponse {
						v[key] = "ri-" + strings.Repeat("4", 32)
					}
				case "parent_identity_id":
					v[key] = "ri-" + strings.Repeat("3", 32)
				case "instance_id":
					v[key] = "hi-" + strings.Repeat("1", 32)
				case "agent_id":
					v[key] = "hri-" + strings.Repeat("1", 32)
				case "grant_id":
					v[key] = "grt-native-readback-fixture"
				case "admission_id":
					v[key] = "adm-native-readback-fixture"
				case "permission_digest", "parent_sha256", "issuer_sha256":
					v[key] = strings.Repeat("a", 64)
				case "binding_id":
					v[key] = "bind-" + strings.Repeat("b", 64)
				case "intent_id":
					v[key] = "int-ri-" + strings.Repeat("b", 64)
				case "credential_path":
					v[key] = "/synthetic/credential.token"
				case "created_at":
					v[key] = "2026-10-07T00:00:00Z"
				case "expires_at":
					v[key] = "2026-10-07T00:04:00Z"
				case "session_ttl_seconds":
					v[key] = float64(240)
				default:
					normalize(child)
				}
			}
		}
	}
	normalize(parsed)
	path := filepath.Join("../../testdata/contracts", name+".sample.json")
	if os.Getenv("SIQ_UPDATE_NATIVE_READBACK_FIXTURES") == "1" {
		b, _ := json.MarshalIndent(parsed, "", "  ")
		if err := os.WriteFile(path, append(b, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	assertRequestSample(t, name+".sample", parsed)
}

func TestNativeIdentityListVersionKeepsStrongestContract(t *testing.T) {
	legacy := runtimeidentity.Summary{}
	windows := runtimeidentity.Summary{FilesystemProfile: "windows-local-drive/v1"}
	native := runtimeidentity.Summary{NativeSkillPolicy: &runtimeidentity.NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: strings.Repeat("c", 64)}}
	for _, rows := range [][]runtimeidentity.Summary{{native, windows, legacy}, {legacy, windows, native}, {windows, native, legacy}} {
		if runtimeIdentityListVersion(rows) != "local-runtime-identities/v3" {
			t.Fatal("native response downgraded by ordering")
		}
	}
	if runtimeIdentityListVersion([]runtimeidentity.Summary{windows, legacy}) != "local-runtime-identities/v2" || runtimeIdentityListVersion([]runtimeidentity.Summary{legacy}) != "local-runtime-identities/v1" {
		t.Fatal("legacy/Windows response version changed")
	}
}
