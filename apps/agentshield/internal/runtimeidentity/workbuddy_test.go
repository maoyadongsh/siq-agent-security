package runtimeidentity

import (
	"encoding/json"
	"os"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestWorkBuddyNativeIdentitySharedVectors(t *testing.T) {
	raw, err := os.ReadFile("../../../../packages/contracts/fixtures/workbuddy_native_identity_v1_examples.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		HostSession string `json:"host_session_id"`
		HostCall    string `json:"host_call_id"`
		Session     string `json:"session_id"`
		Call        string `json:"tool_call_id"`
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		session, err := WorkBuddySessionID(c.HostSession)
		if err != nil || session != c.Session {
			t.Fatal("session vector", err)
		}
		call, err := WorkBuddyCallID(c.HostSession, c.HostCall)
		if err != nil || call != c.Call || !ValidWorkBuddyCallID(call) {
			t.Fatal("call vector", err)
		}
		other, _ := WorkBuddyCallID("other-session", c.HostCall)
		if other == call || ValidWorkBuddyCallID(session) {
			t.Fatal("namespace collision")
		}
	}
}

func TestWorkBuddyNativeIdentityRejectsInvalidAndLegacyProfile(t *testing.T) {
	for _, bad := range []string{"", " leading", "trailing ", "a\x00b", "a\u0085b", string([]byte{0xff}), strings.Repeat("x", 257), strings.Repeat("界", 86)} {
		if _, err := WorkBuddySessionID(bad); err == nil {
			t.Fatal("invalid raw session accepted")
		}
		if _, err := WorkBuddyCallID("valid", bad); err == nil {
			t.Fatal("invalid raw call accepted")
		}
	}
	session, _ := WorkBuddySessionID("host")
	r := Record{SchemaVersion: "local-runtime-identity/v1", Platform: "workbuddy"}
	if validRecordProfile(r) || validateManagedSession(r, session) == nil {
		t.Fatal("legacy WorkBuddy identity accepted")
	}
	if _, err := (&Store{}).creationProfile(CreateRequest{SchemaVersion: "local-runtime-identity-create/v1"}, "workbuddy", &grant.Grant{}); err == nil {
		t.Fatal("legacy WorkBuddy creation accepted")
	}
	r.SchemaVersion = "local-runtime-identity/v2"
	r.FilesystemProfile = "windows-local-drive/v1"
	r.GrantRef.PermissionDigestSchema = "grant-permissions/v2"
	if err := validateManagedSession(r, session); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{"host", strings.ToUpper(session), session + "x", "workbuddy-call/v1:" + strings.Repeat("a", 64)} {
		if validateManagedSession(r, bad) == nil {
			t.Fatal("unbounded or foreign session accepted")
		}
	}
	r = Record{SchemaVersion: "local-runtime-identity/v1", Platform: "hermes"}
	if !validRecordProfile(r) || validateManagedSession(r, "legacy-session") != nil {
		t.Fatal("legacy Hermes semantics changed")
	}
}
