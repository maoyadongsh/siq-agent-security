//go:build !windows

package inventory

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestFindConnectorBinNonWindowsLayoutsAndExecuteBits(t *testing.T) {
	for _, rel := range []string{"hermes/hermes-connector", "hermes/hermes", "hermes-connector", "hermes"} {
		t.Run(rel, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, filepath.FromSlash(rel))
			write(t, path, "fixed candidate")
			if got, err := findConnectorBin(root, "hermes"); got != "" || !errors.Is(err, os.ErrNotExist) {
				t.Fatalf("non-executable candidate accepted: %q, %v", got, err)
			}
			if err := os.Chmod(path, 0o755); err != nil {
				t.Fatal(err)
			}
			if got, err := findConnectorBin(root, "hermes"); got != path || err != nil {
				t.Fatalf("executable candidate missing: %q, %v; want %q", got, err, path)
			}
		})
	}
}

func TestFindConnectorBinNonWindowsPriority(t *testing.T) {
	root := t.TempDir()
	paths := []string{filepath.Join(root, "hermes", "hermes-connector"), filepath.Join(root, "hermes", "hermes"), filepath.Join(root, "hermes-connector")}
	for _, path := range paths {
		write(t, path, "fixed candidate")
		if err := os.Chmod(path, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	for _, want := range paths {
		if got, err := findConnectorBin(root, "hermes"); got != want || err != nil {
			t.Fatalf("got %q, %v; want %q", got, err, want)
		}
		if err := os.Remove(want); err != nil {
			t.Fatal(err)
		}
	}
	// The fourth candidate shares the nested candidates' directory name.
	if got, err := findConnectorBin(root, "hermes"); got != "" || !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("directory accepted: %q, %v", got, err)
	}
	last := filepath.Join(root, "hermes")
	if err := os.Remove(last); err != nil {
		t.Fatal(err)
	}
	write(t, last, "fixed candidate")
	if err := os.Chmod(last, 0o755); err != nil {
		t.Fatal(err)
	}
	if got, err := findConnectorBin(root, "hermes"); got != last || err != nil {
		t.Fatalf("fourth candidate missing: %q, %v", got, err)
	}
}
