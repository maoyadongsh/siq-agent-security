package adapterinstall

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/state"
)

func reinstallWorkBuddyIdentity(t *testing.T, o Options) Options {
	t.Helper()
	o.RuntimeIdentityID = "ri-" + strings.Repeat("d", 32)
	raw, _ := json.Marshal(map[string]any{"schema_version": "local-runtime-identity/v2", "filesystem_profile": "windows-local-drive/v1", "identity_id": o.RuntimeIdentityID, "instance_id": o.Instance.ID, "agent_id": "hri-" + strings.TrimPrefix(o.Instance.ID, "hi-"), "platform": WorkBuddy})
	putTestFile(t, filepath.Join(o.StateDir, "runtime-identities", o.RuntimeIdentityID+".json"), raw, 0600)
	return o
}

func TestWorkBuddyReinstallPreservesHostChangesAndFirstSnapshot(t *testing.T) {
	o := workBuddyManagedOptions(t)
	path := filepath.Join(o.configRoot(), "settings.json")
	original, _ := os.ReadFile(path)
	if _, err := Install(o); err != nil {
		t.Fatal(err)
	}
	putTestFile(t, managedRevocationPath(o), []byte(`{"revoked":true}`), 0600)
	if _, err := Uninstall(o); err != nil {
		t.Fatal(err)
	}
	doc := reflectJSON(t, original)
	doc["claw"] = map[string]any{"legacyOwnerUid": "synthetic-local-owner"}
	changed, _ := json.Marshal(doc)
	putTestFile(t, path, changed, 0600)
	o = reinstallWorkBuddyIdentity(t, o)
	if _, err := Install(o); err != nil {
		t.Fatal("reinstall after host edit", err)
	}
	got, _ := os.ReadFile(path)
	if reflectJSON(t, got)["claw"].(map[string]any)["legacyOwnerUid"] != "synthetic-local-owner" {
		t.Fatal("host edit lost")
	}
	putTestFile(t, managedRevocationPath(o), []byte(`{"revoked":true}`), 0600)
	if _, err := Uninstall(o); err != nil {
		t.Fatal(err)
	}
	got, _ = os.ReadFile(path)
	if !jsonDocumentsEqual(got, changed) {
		t.Fatal("uninstall lost host changes")
	}
	backup, _ := os.ReadFile(path + originalSuffix)
	if !bytes.Equal(backup, original) {
		t.Fatal("first snapshot overwritten")
	}
}

func TestWorkBuddyReinstallRejectsUnprovenSnapshot(t *testing.T) {
	for _, scenario := range []string{"no-history", "changed-snapshot", "wrong-root", "tampered-history"} {
		t.Run(scenario, func(t *testing.T) {
			o := workBuddyManagedOptions(t)
			path := filepath.Join(o.configRoot(), "settings.json")
			if scenario != "no-history" {
				if _, err := Install(o); err != nil {
					t.Fatal(err)
				}
				putTestFile(t, managedRevocationPath(o), []byte(`{"revoked":true}`), 0600)
				if _, err := Uninstall(o); err != nil {
					t.Fatal(err)
				}
			}
			if scenario == "wrong-root" {
				root := filepath.Join(o.Home, "other-workbuddy")
				t.Setenv("WORKBUDDY_CONFIG_DIR", root)
				o = WithWorkBuddyInstance(o, root)
				path = filepath.Join(root, "settings.json")
			}
			putTestFile(t, path, []byte(`{"host_setting":"current"}`), 0600)
			if scenario != "tampered-history" {
				putTestFile(t, path+originalSuffix, []byte(`{"host_setting":"unproven"}`), 0600)
			}
			if scenario == "tampered-history" {
				_, raw, err := (&state.Store{Dir: o.StateDir}).LatestSeq("adapter-operations", operationKey(o))
				if err != nil {
					t.Fatal(err)
				}
				var claim operationClaim
				if err := json.Unmarshal(raw, &claim); err != nil {
					t.Fatal(err)
				}
				putTestFile(t, transactionPath(o.StateDir, claim.ID, ".sealed"), []byte("not authenticated"), 0600)
			}
			before, _ := os.ReadFile(path)
			backup, _ := os.ReadFile(path + originalSuffix)
			o = reinstallWorkBuddyIdentity(t, o)
			if _, err := Prepare(o, "install"); err == nil {
				t.Fatal("unproven snapshot accepted")
			}
			after, _ := os.ReadFile(path)
			backupAfter, _ := os.ReadFile(path + originalSuffix)
			if !bytes.Equal(before, after) || !bytes.Equal(backup, backupAfter) {
				t.Fatal("refused preview changed files")
			}
		})
	}
}
