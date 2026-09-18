package effectevidence

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func profileSnapshotFixture() FileSnapshot {
	return FileSnapshot{SchemaVersion: "file-snapshot/v2", FilesystemProfile: "windows-local-drive/v1", IdentityDigest: strings.Repeat("a", 64), ParentIdentityDigest: strings.Repeat("b", 64), ResourceRef: "filesystem:sha256:" + strings.Repeat("c", 64), CapturedAt: "2026-09-18T00:00:00Z"}
}

func profilePendingFixture() PendingFile {
	return PendingFile{SchemaVersion: "file-observation-pending/v2", IntentID: "int-fixture", IntentDigest: strings.Repeat("d", 64), ID: "profile-pending", ActionID: "action-fixture", ReceiptID: "receipt-fixture", Scope: provenance.Scope{Platform: "hermes", SessionID: "s-fixture", AgentID: "a-fixture", TaskID: "task-fixture"}, Source: Source{Type: "host_observer", SourceID: "component-fixture", Independence: "host_independent"}, Before: profileSnapshotFixture(), OwnerDigest: strings.Repeat("e", 64), ExpectedDigest: strings.Repeat("f", 64), MaxBytes: 1024, ExpiresAt: "2099-01-01T00:00:00Z", SigningSchema: "local_canonical/v1"}
}

func TestFileProfileV2RejectsMixedInterpretation(t *testing.T) {
	before := profileSnapshotFixture()
	after := before
	after.Exists, after.Digest, after.Size = true, strings.Repeat("d", 64), 3
	after.MTime, after.CapturedAt = "2026-09-18T00:00:01Z", "2026-09-18T00:00:02Z"
	after.IdentityDigest = strings.Repeat("e", 64)
	if material, err := FileWrite(before, after, after.Digest); err != nil || material.SchemaVersion != "file-observation/v2" || material.Result != "expected" {
		t.Fatal("new leaf rejected", material, err)
	}
	for _, kind := range []string{"profile", "parent", "resource", "missing-identity", "legacy-after"} {
		t.Run(kind, func(t *testing.T) {
			bad := after
			switch kind {
			case "profile":
				bad.FilesystemProfile = "posix/v1"
			case "parent":
				bad.ParentIdentityDigest = strings.Repeat("f", 64)
			case "resource":
				bad.ResourceRef = "filesystem:sha256:" + strings.Repeat("f", 64)
			case "missing-identity":
				bad.IdentityDigest = ""
			case "legacy-after":
				bad.SchemaVersion, bad.FilesystemProfile, bad.IdentityDigest, bad.ParentIdentityDigest = "", "", "", ""
			}
			if _, err := FileWrite(before, bad, after.Digest); !errors.Is(err, ErrFileObservation) {
				t.Fatal("mixed observation accepted", err)
			}
		})
	}
	if _, err := CaptureFileForProfile(runtimeaction.FilesystemProfile("unknown/v1"), "C:/untrusted", 1024); !errors.Is(err, ErrFileObservation) {
		t.Fatal("unknown profile inferred", err)
	}
}

func TestFileProfileDecodersRejectVersionSmuggling(t *testing.T) {
	legacy := profileSnapshotFixture()
	legacy.SchemaVersion, legacy.FilesystemProfile, legacy.IdentityDigest, legacy.ParentIdentityDigest = "", "", "", ""
	raw, _ := json.Marshal(legacy)
	for _, extra := range []string{`"schema_version":""`, `"schema_version":null`, `"filesystem_profile":""`, `"filesystem_profile":null`, `"identity_digest":""`, `"parent_identity_digest":null`, `"exists":true`} {
		var decoded FileSnapshot
		if json.Unmarshal(append(append([]byte{}, raw[:len(raw)-1]...), []byte(","+extra+"}")...), &decoded) == nil {
			t.Fatal("legacy extension or duplicate accepted", extra)
		}
	}
	v2, _ := json.Marshal(profileSnapshotFixture())
	for _, old := range []string{`"file-snapshot/v2"`, `"windows-local-drive/v1"`, `"` + strings.Repeat("a", 64) + `"`} {
		var decoded FileSnapshot
		if json.Unmarshal(bytes.Replace(v2, []byte(old), []byte("null"), 1), &decoded) == nil {
			t.Fatal("required interpretation field null accepted", old)
		}
	}
}

func TestFileProfileLegacyWireAndSignatureStable(t *testing.T) {
	// Independent pre-v2 wire bytes: none of the new interpretation fields is present.
	const oldSnapshot = `{"resource_ref":"filesystem:sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","exists":false,"digest":"","size":0,"mtime":"","captured_at":"2026-09-18T00:00:00Z"}`
	var snapshot FileSnapshot
	if err := json.Unmarshal([]byte(oldSnapshot), &snapshot); err != nil {
		t.Fatal(err)
	}
	encoded, _ := json.Marshal(snapshot)
	if string(encoded) != oldSnapshot {
		t.Fatal("legacy snapshot wire changed", string(encoded))
	}
	p := profilePendingFixture()
	p.SchemaVersion, p.IntentID, p.IntentDigest, p.Before = "file-observation-pending/v1", "", "", snapshot
	const oldPending = `{"schema_version":"file-observation-pending/v1","observation_id":"profile-pending","action_id":"action-fixture","decision_receipt_id":"receipt-fixture","scope":{"platform":"hermes","session_id":"s-fixture","agent_id":"a-fixture","task_id":"task-fixture"},"source":{"type":"host_observer","source_id":"component-fixture","independence":"host_independent"},"before":` + oldSnapshot + `,"owner_digest":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","expected_digest":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff","max_bytes":1024,"expires_at":"2099-01-01T00:00:00Z","signing_schema":"local_canonical/v1","signature":""}`
	encoded, _ = json.Marshal(p)
	if string(encoded) != oldPending {
		t.Fatal("legacy pending wire changed")
	}
	old, err := canon.Decode([]byte(oldPending))
	if err != nil {
		t.Fatal(err)
	}
	unsigned := old.(map[string]any)
	delete(unsigned, "signature")
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	want, err := key.SignCanonical(unsigned)
	if err != nil {
		t.Fatal(err)
	}
	got, err := key.SignCanonical(p.unsigned())
	if err != nil || got != want {
		t.Fatal("legacy signed bytes changed", err)
	}
	p.Signature = want
	encoded, _ = json.Marshal(p)
	var decoded PendingFile
	if json.Unmarshal(encoded, &decoded) != nil || !signing.VerifyCanonical(key.Public(), decoded.unsigned(), decoded.Signature) {
		t.Fatal("historical pending no longer verifies")
	}
	observation, err := FileWrite(snapshot, snapshot, p.ExpectedDigest)
	if err != nil {
		t.Fatal(err)
	}
	const oldMaterial = `{"before":` + oldSnapshot + `,"after":` + oldSnapshot + `,"expected_digest":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff","execution_state":"failed","result":"unexpected"}`
	encoded, _ = json.Marshal(observation)
	if string(encoded) != oldMaterial {
		t.Fatal("legacy material wire changed")
	}
}

func TestFileProfilePendingCannotReadOrRecoverWithoutBarrier(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	store, err := NewStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	p := profilePendingFixture()
	if _, err := store.SavePendingFile(p); !errors.Is(err, ErrState) {
		t.Fatal("new pending published without profile activation", err)
	}
	// Model a copied valid v2 record in legacy state. It must not be usable even
	// though its signature verifies; recovery must not create a history directory.
	dir, err := store.pendingDir()
	if err != nil {
		t.Fatal(err)
	}
	p.Signature, err = key.SignCanonical(p.unsigned())
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(p)
	if err := os.WriteFile(filepath.Join(dir, p.ID+".json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := store.GetPendingFile(p.ID); !errors.Is(err, ErrState) {
		t.Fatal("copied new pending readable under old state", err)
	}
	if _, err := store.RecoverPendingFile(p.ID, p.OwnerDigest, strings.Repeat("a", 64), time.Now()); !errors.Is(err, ErrState) {
		t.Fatal("recovery bypassed profile activation", err)
	}
	if _, err := os.Stat(filepath.Join(dir, p.ID+".recoveries")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("rejected recovery changed durable state", err)
	}
}
