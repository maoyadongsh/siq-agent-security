package server

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestFileObservationRecoveryRequestProfiles(t *testing.T) {
	const old = `{"observation_id":"sample","observer_id":"observer-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expected_owner":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}`
	const next = `{"schema_version":"file-observation-recovery-request/v2","path":"C:/Scope/output.txt","observation_id":"sample","observer_id":"observer-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expected_owner":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}`
	for _, raw := range []string{old, next} {
		var value fileObservationRecoveryRequest
		if err := json.Unmarshal([]byte(raw), &value); err != nil {
			t.Fatal("valid version rejected", err)
		}
		encoded, err := json.Marshal(value)
		if err != nil || string(encoded) != raw {
			t.Fatal("wire version changed", string(encoded), err)
		}
	}
	for _, raw := range []string{
		strings.Replace(old, `"observation_id"`, `"schema_version":"","observation_id"`, 1),
		strings.Replace(old, `"observation_id"`, `"path":"C:/Scope/output.txt","observation_id"`, 1),
		strings.Replace(next, `"path":"C:/Scope/output.txt",`, "", 1),
		strings.Replace(next, `"path":"C:/Scope/output.txt"`, `"path":null`, 1),
		strings.Replace(next, `"path":"C:/Scope/output.txt"`, `"path":""`, 1),
		strings.Replace(next, "request/v2", "request/v99", 1),
		strings.Replace(next, `"path":`, `"filesystem_profile":"windows-local-drive/v1","path":`, 1),
		strings.Replace(next, `"path":`, `"path":"C:/Other/file","path":`, 1),
	} {
		var value fileObservationRecoveryRequest
		if json.Unmarshal([]byte(raw), &value) == nil {
			t.Fatal("unbound recovery interpretation accepted", raw)
		}
	}
}

func TestFileObservationRequiresExactLiveIntent(t *testing.T) {
	for _, kind := range []string{"valid", "wrong-digest", "missing-digest", "wrong-session", "revoked-intent", "revoked-binding", "expired"} {
		t.Run(kind, func(t *testing.T) {
			s, _ := newServer(t, "warn")
			c := apiIntent()
			if kind == "expired" {
				c.ExpiresAt = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
			}
			issued, err := s.intents.Issue(c)
			if err != nil {
				t.Fatal(err)
			}
			a := effectevidence.Action{IntentID: issued.IntentID, IntentDigest: issued.Digest, TaskID: issued.TaskID, Platform: issued.Agent.Platform, AgentID: issued.Agent.ID, SessionID: "file-profile-session"}
			if kind != "expired" {
				b, err := s.intents.Bind(intent.Binding{Platform: a.Platform, AgentID: a.AgentID, SessionID: a.SessionID, IntentID: a.IntentID})
				if err != nil {
					t.Fatal(err)
				}
				if kind == "revoked-binding" {
					if _, err := s.intents.RevokeBinding(b.BindingID, issued.Digest); err != nil {
						t.Fatal(err)
					}
				}
			}
			switch kind {
			case "wrong-digest":
				a.IntentDigest = strings.Repeat("f", 64)
			case "missing-digest":
				a.IntentDigest = ""
			case "wrong-session":
				a.SessionID = "unbound-session"
			case "revoked-intent":
				if _, err := s.intents.RevokeIntent(issued.IntentID, issued.Digest); err != nil {
					t.Fatal(err)
				}
			}
			profile, err := s.fileActionProfile(a)
			if kind == "valid" {
				if err != nil || profile != runtimeaction.FilesystemPOSIXV1 {
					t.Fatal("verified authority rejected", profile, err)
				}
				return
			}
			if err == nil {
				t.Fatal("invalid authority accepted", kind)
			}
		})
	}
}

func TestFileObservationProfileCannotComeFromPathOrPending(t *testing.T) {
	s := &Server{}
	profile, err := s.fileActionProfile(effectevidence.Action{})
	if err != nil || profile != runtimeaction.FilesystemPOSIXV1 {
		t.Fatal("legacy default changed", err)
	}
	if _, err := fileResourceForProfile(profile, "C:/Scope/output.txt"); err == nil {
		t.Fatal("Windows interpretation inferred without Intent")
	}
	a := effectevidence.Action{IntentID: "int-signed", IntentDigest: strings.Repeat("a", 64)}
	p := effectevidence.PendingFile{SchemaVersion: "file-observation-pending/v2", IntentID: a.IntentID, IntentDigest: a.IntentDigest, Before: effectevidence.FileSnapshot{SchemaVersion: "file-snapshot/v2", FilesystemProfile: "windows-local-drive/v1"}}
	if !pendingFileAuthorityMatches(p, a, runtimeaction.FilesystemWindowsLocalDriveV1) {
		t.Fatal("exact v2 binding rejected")
	}
	for _, kind := range []string{"digest", "intent", "profile", "version"} {
		bad := p
		switch kind {
		case "digest":
			bad.IntentDigest = strings.Repeat("b", 64)
		case "intent":
			bad.IntentID = "int-other"
		case "profile":
			bad.Before.FilesystemProfile = "posix/v1"
		case "version":
			bad.SchemaVersion = "file-observation-pending/v1"
		}
		if pendingFileAuthorityMatches(bad, a, runtimeaction.FilesystemWindowsLocalDriveV1) {
			t.Fatal("pending shifted authority", kind)
		}
	}
}
