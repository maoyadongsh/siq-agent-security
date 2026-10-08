package main

import (
	"crypto/sha256"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"
)

var nativeConnectorFixture struct {
	sync.Once
	raw []byte
	err error
}

func connectorFixture(t *testing.T) (string, string) {
	t.Helper()
	nativeConnectorFixture.Do(func() {
		root, err := os.MkdirTemp("", "siq-connector-build-")
		if err != nil {
			nativeConnectorFixture.err = err
			return
		}
		defer os.RemoveAll(root)
		binary := filepath.Join(root, "connector")
		cmd := exec.Command("go", "build", "-o", binary, "./testdata/connector-helper")
		if raw, err := cmd.CombinedOutput(); err != nil {
			nativeConnectorFixture.err = fmt.Errorf("fixture build failed: %s", raw)
			return
		}
		nativeConnectorFixture.raw, nativeConnectorFixture.err = os.ReadFile(binary)
	})
	if nativeConnectorFixture.err != nil {
		t.Fatal(nativeConnectorFixture.err)
	}
	private := t.TempDir()
	if err := os.Chmod(private, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(private, "hermes-connector")
	if err := os.WriteFile(path, nativeConnectorFixture.raw, 0500); err != nil {
		t.Fatal(err)
	}
	return path, fmt.Sprintf("%x", sha256.Sum256(nativeConnectorFixture.raw))
}
