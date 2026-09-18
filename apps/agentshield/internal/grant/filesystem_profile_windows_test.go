package grant

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func windowsResources(t *testing.T) (Grant, ResourceEdit, string) {
	t.Helper()
	root := filepath.Join(t.TempDir(), "确认范围")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", root)
	if err != nil {
		t.Fatal(err)
	}
	g := build(t, "hermes", sampleAdmission()).Grant
	input := ResourceEdit{Tools: []string{"read_file", "write_file"}, Network: []NetworkPatch{}, Models: []string{}, Filesystem: FilesystemPatch{ReadOnly: []string{}, ReadWrite: []string{canonical}}}
	return g, input, root
}

func TestWindowsGrantSignedScopeAndExplicitConfirmation(t *testing.T) {
	g, input, _ := windowsResources(t)
	before, _ := json.Marshal(g)
	oldDigest, _ := PermissionDigest(g)
	if _, _, err := PrepareWindowsResources(g, input, false, key(t)); err != ErrFilesystemProfile {
		t.Fatal("unconfirmed interpretation accepted")
	}
	out, _, err := PrepareWindowsResources(g, input, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	after, _ := json.Marshal(g)
	if !bytes.Equal(before, after) {
		t.Fatal("legacy object changed")
	}
	if out.Status != "pending_approval" || out.ApprovedBy != nil || out.EffectiveReadback != nil || !Verify(key(t).Public(), out) || RecheckFilesystemBindings(out) != nil {
		t.Fatal("incorrect signed draft")
	}
	digest, err := PermissionDigest(out)
	if err != nil || digest == oldDigest {
		t.Fatal("new interpretation reused old digest")
	}
	if _, err := Approve(out, Approval{ActorType: "model", ActorID: "untrusted"}, key(t)); err == nil {
		t.Fatal("model approved resources")
	}
	approved, err := Approve(out, human(), key(t))
	if err != nil || approved.Status != "approved" {
		t.Fatalf("human approval: %v", err)
	}
	if _, _, err := PrepareWindowsResources(approved, input, true, key(t)); err == nil {
		t.Fatal("approved grant silently reinterpreted")
	}
	for id := range *out.FilesystemBindings {
		(*out.FilesystemBindings)[id] = "0000000000000000000000000000000000000000000000000000000000000000"
		break
	}
	if Verify(key(t).Public(), out) {
		t.Fatal("identity binding not signed")
	}
}

func TestWindowsGrantReplacementInvalidatesApprovalButNotRevocation(t *testing.T) {
	g, input, root := windowsResources(t)
	out, _, err := PrepareWindowsResources(g, input, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	approved, err := Approve(out, human(), key(t))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(root, root+"-old"); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	if !Verify(key(t).Public(), out) {
		t.Fatal("historical signature depends on live filesystem")
	}
	if RecheckFilesystemBindings(out) != ErrFilesystemProfile {
		t.Fatal("same-name replacement accepted")
	}
	if _, err := Approve(out, human(), key(t)); err != ErrFilesystemProfile {
		t.Fatal("stale approval accepted")
	}
	if revoked, err := Revoke(approved, key(t)); err != nil || !Verify(key(t).Public(), revoked) {
		t.Fatal("replacement prevented revocation")
	}
	updated, _, err := EditResources(out, input, key(t))
	if err != nil {
		t.Fatal(err)
	}
	previous, _ := PermissionDigest(out)
	next, _ := PermissionDigest(updated)
	if previous == next || RecheckFilesystemBindings(updated) != nil || updated.Status != "pending_approval" {
		t.Fatal("explicit pending edit retained stale binding")
	}
}

func TestWindowsGrantPreservesDenialsAndRejectsUnsupportedLegacyPaths(t *testing.T) {
	for _, path := range []string{"*", "/old-posix-denial"} {
		t.Run(path, func(t *testing.T) {
			g, input, _ := windowsResources(t)
			g.Facts = append(g.Facts, Fact{FactID: "deny", Domain: "filesystem", Action: "fs.write", Resource: admission.Resource{Type: "path", Value: path}, Effect: "deny", State: "declared"})
			resign(key(t), &g)
			out, _, err := PrepareWindowsResources(g, input, true, key(t))
			if path != "*" {
				if err != ErrFilesystemProfile {
					t.Fatal("uninterpretable denial silently removed")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			found := false
			for _, f := range out.Facts {
				if f.FactID == "deny" && f.Effect == "deny" && f.Resource.Value == "*" {
					found = true
				}
			}
			if !found {
				t.Fatal("wildcard denial lost")
			}
		})
	}
}

func TestWindowsGrantMissingOrExtraBindingsAreNotValidAuthority(t *testing.T) {
	g, input, _ := windowsResources(t)
	out, _, err := PrepareWindowsResources(g, input, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, change := range []string{"missing", "extra", "unknown-profile", "old-schema"} {
		t.Run(change, func(t *testing.T) {
			raw, _ := json.Marshal(out)
			var current Grant
			if err := json.Unmarshal(raw, &current); err != nil {
				t.Fatal(err)
			}
			switch change {
			case "missing":
				current.FilesystemBindings = nil
			case "extra":
				(*current.FilesystemBindings)["unknown"] = "0000000000000000000000000000000000000000000000000000000000000000"
			case "unknown-profile":
				current.FilesystemProfile = "unknown"
			case "old-schema":
				current.SchemaVersion = ""
			}
			resign(key(t), &current)
			if Verify(key(t).Public(), current) {
				t.Fatal("signed malformed shape accepted")
			}
			if _, err := PermissionDigest(current); err == nil {
				t.Fatal("malformed permissions digested")
			}
		})
	}
}

func TestWindowsGrantChallengeBindsFileIdentity(t *testing.T) {
	g, input, _ := windowsResources(t)
	original, _, err := PrepareWindowsResources(g, input, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	when := time.Now().UTC()
	challenge, err := IssueChallenge(original, 3, when)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(original)
	var changed Grant
	if err := json.Unmarshal(raw, &changed); err != nil {
		t.Fatal(err)
	}
	for id := range *changed.FilesystemBindings {
		(*changed.FilesystemBindings)[id] = "0000000000000000000000000000000000000000000000000000000000000000"
		break
	}
	resign(key(t), &changed)
	t.Run("binding-digest", func(t *testing.T) {
		a, _ := BindingDigest(original)
		b, _ := BindingDigest(changed)
		if a == b {
			t.Fatal("approval binding digest omitted filesystem identity")
		}
	})
	t.Run("scope-digest", func(t *testing.T) {
		a, _ := ScopeDigest(original)
		b, _ := ScopeDigest(changed)
		if a == b {
			t.Fatal("approval scope digest omitted filesystem identity")
		}
	})
	t.Run("challenge", func(t *testing.T) {
		if err := ValidateChallenge(*challenge, changed, 3, challenge.Nonce, when); err != ErrChallengeMismatch {
			t.Fatal("stale challenge accepted a changed filesystem identity")
		}
	})
}

func TestWindowsGrantStrictWire(t *testing.T) {
	g, input, _ := windowsResources(t)
	out, _, err := PrepareWindowsResources(g, input, true, key(t))
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(out)
	for _, addition := range []string{`,"ignored":true}`, `,"FACTS":[]}`, `,"filesystem_profile":"windows-local-drive/v1"}`} {
		changed := append(append([]byte{}, raw[:len(raw)-1]...), []byte(addition)...)
		var decoded Grant
		if json.Unmarshal(changed, &decoded) == nil {
			t.Fatal("unknown, aliased or duplicated new Grant field accepted")
		}
	}
	var decoded Grant
	if err := json.Unmarshal(raw, &decoded); err != nil || !Verify(key(t).Public(), decoded) {
		t.Fatalf("valid new Grant roundtrip failed: %v", err)
	}
}
