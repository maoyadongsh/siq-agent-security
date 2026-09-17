package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func windowsTaskBootstrapFixture(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv(product.EnvStateDir, dir)
	t.Setenv(product.EnvSigningSeed, "")
	t.Setenv(product.EnvSigningSeedOld, "")
	if err := cmdInitialize(nil, io.Discard); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestWindowsTaskPrepareFirstIdentity(t *testing.T) {
	dir := windowsTaskBootstrapFixture(t)
	seed := filepath.Join(dir, "keys", "signing.seed")
	if _, err := os.Stat(seed); !os.IsNotExist(err) {
		t.Fatal("fixture must start without an identity")
	}
	var first, second bytes.Buffer
	if err := cmdWindowsTaskPrepare(nil, &first); err != nil {
		t.Fatal(err)
	}
	k, err := signing.LoadExisting(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := cmdWindowsTaskPrepare(nil, &second); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first.Bytes(), second.Bytes()) {
		t.Fatal("repeat preparation changed signed ownership")
	}
	again, err := signing.LoadExisting(dir)
	if err != nil || again.PublicBase64() != k.PublicBase64() {
		t.Fatal("repeat preparation replaced identity")
	}
	// No system registration API is called by task-prepare.
}

func TestWindowsTaskPrepareMissingIdentityRefusesHistory(t *testing.T) {
	for _, history := range []string{"grants/history.json", "unknown-state.json"} {
		t.Run(history, func(t *testing.T) {
			dir := windowsTaskBootstrapFixture(t)
			path := filepath.Join(dir, history)
			if err := os.WriteFile(path, []byte("owned historical sentinel"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := cmdWindowsTaskPrepare(nil, io.Discard); !errors.Is(err, signing.ErrIdentityMissing) {
				t.Fatalf("missing historical identity not rejected: %v", err)
			}
			for _, name := range []string{"keys/signing.seed", "windows-task.json"} {
				if _, err := os.Lstat(filepath.Join(dir, name)); !os.IsNotExist(err) {
					t.Fatal("rejected preparation published identity or task record")
				}
			}
			if raw, err := os.ReadFile(path); err != nil || string(raw) != "owned historical sentinel" {
				t.Fatal("history changed during rejection")
			}
		})
	}
}

func TestWindowsTaskPrepareLostEstablishedIdentity(t *testing.T) {
	dir := windowsTaskBootstrapFixture(t)
	if _, err := signing.Load(dir); err != nil {
		t.Fatal(err)
	}
	if err := cmdWindowsTaskPrepare(nil, io.Discard); err != nil {
		t.Fatal(err)
	}
	record := filepath.Join(dir, "windows-task.json")
	before, err := os.ReadFile(record)
	if err != nil {
		t.Fatal(err)
	}
	seed := filepath.Join(dir, "keys/signing.seed")
	if err := os.Remove(seed); err != nil {
		t.Fatal(err)
	}
	if err := cmdWindowsTaskPrepare(nil, io.Discard); !errors.Is(err, signing.ErrIdentityMissing) {
		t.Fatalf("lost established identity not rejected: %v", err)
	}
	if _, err := os.Lstat(seed); !os.IsNotExist(err) {
		t.Fatal("established identity was recreated")
	}
	if after, err := os.ReadFile(record); err != nil || !bytes.Equal(before, after) {
		t.Fatal("signed ownership record changed")
	}
}

func TestWindowsTaskPrepareBootstrapWriterConflict(t *testing.T) {
	for _, scoped := range []bool{false, true} {
		t.Run(map[bool]string{false: "primary", true: "lifecycle"}[scoped], func(t *testing.T) {
			dir := windowsTaskBootstrapFixture(t)
			var w *state.Writer
			var err error
			if scoped {
				w, err = state.AcquireScopedWriter(dir, "service-control")
			} else {
				w, err = state.AcquireWriter(dir)
			}
			if err != nil {
				t.Fatal(err)
			}
			defer w.Release()
			if err := cmdWindowsTaskPrepare(nil, io.Discard); err == nil {
				t.Fatal("conflicting preparation accepted")
			}
			if _, err := os.Lstat(filepath.Join(dir, "keys/signing.seed")); !os.IsNotExist(err) {
				t.Fatal("conflicting preparation created identity")
			}
		})
	}
}
