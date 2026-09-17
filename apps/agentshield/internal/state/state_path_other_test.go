//go:build !windows

package state

import (
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/product"
)

func TestNonWindowsStatePathBehaviorUnchanged(t *testing.T) {
	t.Setenv(product.EnvStateDir, "  primary  ")
	t.Setenv(product.EnvStateDirOld, " legacy ")
	if got, err := DefaultDir(); err != nil || got != "primary" {
		t.Fatal("primary trimming changed")
	}
	t.Setenv(product.EnvStateDir, "   ")
	if got, err := DefaultDir(); err != nil || got != "legacy" {
		t.Fatal("legacy fallback changed")
	}
	for _, name := range []string{"target.", "target "} {
		st, err := Open(filepath.Join(t.TempDir(), name))
		if err != nil {
			t.Fatal(err)
		}
		if _, err := st.Token(); err != nil {
			t.Fatal(err)
		}
	}
}
