package adapterinstall

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func TestWindowsStatePathAdapterTransactionRoots(t *testing.T) {
	parent := t.TempDir()
	target := filepath.Join(parent, "target")
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	opts := Options{Platform: Trae, Home: parent, StateDir: target}
	if _, err := Prepare(opts, "install"); err != nil {
		t.Fatal("valid transaction state rejected")
	}
	for _, raw := range []string{target + ".", target + " ", parent + `\bad.\..\target`} {
		opts.StateDir = raw
		if p, err := Prepare(opts, "install"); p != nil || !errors.Is(err, stateformat.ErrCorrupt) {
			t.Error("prepare accepted invalid raw state")
		}
		if r, err := Recover(raw, Trae); r != nil || !errors.Is(err, stateformat.ErrCorrupt) {
			t.Error("recover accepted invalid raw state")
		}
		if entries, err := os.ReadDir(target); err != nil || len(entries) != 0 {
			t.Fatal("rejected transaction changed state")
		}
	}
}
