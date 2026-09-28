package adapterinstall

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/state"
)

func TestWorkBuddyUninstallReadbackPreservesHostSettings(t *testing.T) {
	o := testOpts(t, WorkBuddy)
	root := configDir(o.Home, WorkBuddy)
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "settings.json")
	original := []byte(`{"enabledPlugins":{"builtin":true},"user_setting":"keep","hooks":{"PreToolUse":[{"matcher":"Read","hooks":[{"type":"command","command":"echo third-party"}]}]}}`)
	putTestFile(t, path, original, 0600)
	if _, err := Install(o); err != nil {
		t.Fatal(err)
	}
	installed, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Uninstall(o); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(path)
	if err != nil || string(after) != string(original) {
		t.Fatal("host settings changed", err)
	}
	d := Inspect(o)
	if d.ConfigurationState != "not_installed" || d.RuntimeState != "unverified" {
		t.Fatalf("successful uninstall reported as failure: %+v", d)
	}
	_, raw, err := (&state.Store{Dir: o.StateDir}).LatestSeq("adapter-operations", operationKey(o))
	var claim operationClaim
	if err != nil || json.Unmarshal(raw, &claim) != nil {
		t.Fatal("missing operation", err)
	}
	for _, suffix := range []string{".end.json", ".sealed"} {
		t.Run("invalid"+suffix, func(t *testing.T) {
			file := transactionPath(o.StateDir, claim.ID, suffix)
			saved, err := os.ReadFile(file)
			if err != nil {
				t.Fatal(err)
			}
			defer putTestFile(t, file, saved, 0600)
			putTestFile(t, file, []byte("tampered"), 0600)
			if Inspect(o).ConfigurationState == "not_installed" {
				t.Fatal("unverified uninstall accepted")
			}
		})
	}
	endPath := transactionPath(o.StateDir, claim.ID, ".end.json")
	end, err := os.ReadFile(endPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(endPath); err != nil {
		t.Fatal(err)
	}
	if Inspect(o).ConfigurationState == "not_installed" {
		t.Fatal("unfinished uninstall accepted")
	}
	putTestFile(t, endPath, end, 0600)
	if !workBuddyUninstallReadback(o) {
		t.Fatal("restored evidence was not readable")
	}
	// A historical uninstall must not hide hooks restored after that operation.
	putTestFile(t, path, installed, 0600)
	if Inspect(o).ConfigurationState == "not_installed" {
		t.Fatal("restored hook hidden by old uninstall")
	}
}
