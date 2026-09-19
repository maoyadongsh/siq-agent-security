//go:build windows

package adapterinstall

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

// This exercises the production target inspector on real Windows filesystem
// facts and activated state. Program files and the native-installation record
// are metadata fixtures; no host or installation transaction runs, and no
// replacement Snapshot callback is used.
func TestWindowsRuntimeTargetCanonicalProfile(t *testing.T) {
	o := testOpts(t, Hermes)
	// testOpts' pre-existing t.TempDir is suitable for legacy tests; explicit
	// Windows activation needs a newly created private state root (no ACL repair).
	o.StateDir = filepath.Join(o.StateDir, "private-state")
	st, err := state.Open(o.StateDir)
	if err != nil {
		t.Fatal(err)
	}
	writer, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	_, initErr := st.Initialize(writer, 47611)
	releaseErr := writer.Release()
	if initErr != nil || releaseErr != nil {
		t.Fatalf("state initialization: %v; release: %v", initErr, releaseErr)
	}
	root := filepath.Join(o.Home, ".hermes")
	o = WithHermesInstance(o, hermeshome.Root{ID: hermeshome.Identifier(root), Name: "default", Path: root})
	o.NativeCLI = filepath.Join(o.Home, "hermes-fixture.exe")
	putTestFile(t, o.NativeCLI, []byte("non-executable native metadata fixture\n"), 0700)
	config := []byte("plugins:\n  enabled: [siq-agent-security]\n  entries:\n    siq-agent-security:\n      allow_tool_override: false\n")
	putTestFile(t, filepath.Join(root, "config.yaml"), config, 0600)
	for _, name := range []string{"plugin.yaml", "__init__.py"} {
		asset, err := embedded.ReadFile("assets/hermes/" + name)
		if err != nil {
			t.Fatal(err)
		}
		putTestFile(t, filepath.Join(root, "plugins", "siq-agent-security", name), asset, 0600)
	}
	connection, err := json.Marshal(map[string]any{"endpoint": o.Endpoint, "token_path": filepath.Join(o.StateDir, "token"), "enforcement_mode": o.Mode, "timeout_s": 5})
	if err != nil {
		t.Fatal(err)
	}
	putTestFile(t, filepath.Join(root, "plugins", "siq-agent-security", "config.json"), connection, 0600)
	image, err := readImage(o.Home, filepath.Join(root, "config.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	nativeHash, err := programDigest(o.NativeCLI)
	if err != nil {
		t.Fatal(err)
	}
	record := Record{Platform: Hermes, InstanceID: o.Instance.ID, ConfigDir: root, Binary: o.Binary,
		InstalledAt: o.Now.Format(time.RFC3339), NativeOriginal: &NativeRegistration{},
		NativeConfigHash: imageHash(image), NativeCLI: o.NativeCLI, NativeCLIHash: nativeHash}
	recordRaw, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	backupDir := filepath.Join(o.StateDir, "backups", "adapters")
	if err := statefs.MkdirAllPrivate(backupDir); err != nil {
		t.Fatal(err)
	}
	if err := statefs.WriteFile(filepath.Join(backupDir, "hermes.20260918.json"), recordRaw, 0600); err != nil {
		t.Fatal(err)
	}
	if d := Inspect(o); d.ConfigurationState != "ready" {
		t.Fatalf("fixture must reach the real profile gate: %+v", d)
	}
	if _, err := InspectRuntimeTarget(o); err == nil || err.Error() != "runtime_check_windows_profile_required" {
		t.Fatalf("unconfirmed Windows state must refuse target: %v", err)
	}
	if _, err := st.ActivateWindowsProfile(true, "runtime-target-canonical-fixture"); err != nil {
		t.Fatal(err)
	}
	t.Log("real Windows state initialized and profile explicitly activated")
	target, err := InspectRuntimeTarget(o)
	if err != nil {
		t.Fatalf("ready Windows target must produce canonical snapshot: %v", err)
	}
	facts, err := runtimepath.InspectWindows(root, false)
	if err != nil {
		t.Fatal(err)
	}
	rootIdentity, err := facts.IdentityDigest()
	if err != nil {
		t.Fatal(err)
	}
	serviceHash, err := programDigest(o.Binary)
	if err != nil {
		t.Fatal(err)
	}
	// Independent JSON-model input: profile is the contract string, not a
	// runtimeaction.FilesystemProfile value hidden behind an interface.
	material := map[string]any{"instance_id": o.Instance.ID, "profile": root, "native_cli": o.NativeCLI,
		"native_sha256": nativeHash, "service_sha256": serviceHash, "mode": o.Mode, "endpoint": o.Endpoint,
		"filesystem_profile": "windows-local-drive/v1", "root_identity_digest": rootIdentity}
	for _, name := range []string{"config.yaml", "plugins/siq-agent-security/plugin.yaml", "plugins/siq-agent-security/__init__.py", "plugins/siq-agent-security/config.json"} {
		data, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(name)))
		if err != nil {
			t.Fatal(err)
		}
		digest := sha256.Sum256(data)
		material[name] = hex.EncodeToString(digest[:])
	}
	canonical, err := canon.Marshal(material)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(canonical)
	if target.InstanceID != o.Instance.ID || target.ProfilePath != root || target.Home != o.Home || target.NativeCLI != o.NativeCLI ||
		target.FilesystemProfile != runtimeaction.FilesystemWindowsLocalDriveV1 || target.RootIdentityDigest != rootIdentity || target.Digest != hex.EncodeToString(digest[:]) {
		t.Fatal("snapshot omitted or changed the profile, physical identity, instance, or canonical file/program hashes")
	}
	t.Log("real inspector snapshot matches independent contract-string canonical bytes")
	putTestFile(t, filepath.Join(root, "config.yaml"), append(append([]byte{}, config...), []byte("# outside edit\n")...), 0600)
	if _, err := InspectRuntimeTarget(o); err == nil {
		t.Fatal("native configuration drift accepted")
	}
	putTestFile(t, filepath.Join(root, "config.yaml"), config, 0600)
	putTestFile(t, o.NativeCLI, []byte("changed native metadata fixture\n"), 0700)
	if _, err := InspectRuntimeTarget(o); err == nil {
		t.Fatal("native launcher drift accepted")
	}
	t.Log("configuration and launcher drift still refused; no native process started")
}
