package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func serviceBootstrapFixture(t *testing.T) string {
	t.Helper()
	if runtime.GOOS != "linux" {
		t.Skip("Linux user service preparation")
	}
	dir := filepath.Join(t.TempDir(), "state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	t.Setenv("SIQ_AGENT_SECURITY_SIGNING_SEED", "")
	t.Setenv("AGENTSHIELD_SIGNING_SEED", "")
	if err := cmdInitialize(nil, io.Discard); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestServicePrepareBootstrapsIdentityBeforeLifecycleLock(t *testing.T) {
	dir := serviceBootstrapFixture(t)
	seed := filepath.Join(dir, "keys", "signing.seed")
	if _, err := os.Lstat(seed); !os.IsNotExist(err) {
		t.Fatal("fixture already has identity")
	}
	var first, second bytes.Buffer
	if err := cmdServicePrepare(nil, &first); err != nil {
		t.Fatal(err)
	}
	key, err := signing.LoadExisting(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := cmdServicePrepare(nil, &second); err != nil {
		t.Fatal(err)
	}
	again, err := signing.LoadExisting(dir)
	if err != nil || again.PublicBase64() != key.PublicBase64() || !bytes.Equal(first.Bytes(), second.Bytes()) {
		t.Fatal("repeat preparation changed established identity or signed unit")
	}
	if err := os.Remove(seed); err != nil {
		t.Fatal(err)
	}
	if err := cmdServicePrepare(nil, io.Discard); !errors.Is(err, signing.ErrIdentityMissing) {
		t.Fatalf("established identity loss not rejected: %v", err)
	}
	if _, err := os.Lstat(seed); !os.IsNotExist(err) {
		t.Fatal("lost established key recreated")
	}
}

func TestServicePrepareBootstrapRefusesHistoryAndWriters(t *testing.T) {
	for _, kind := range []string{"history", "primary", "lifecycle", "corrupt"} {
		t.Run(kind, func(t *testing.T) {
			dir := serviceBootstrapFixture(t)
			var lock *state.Writer
			var err error
			switch kind {
			case "history":
				err = os.WriteFile(filepath.Join(dir, "unknown-history.json"), []byte("historical sentinel"), 0600)
			case "primary":
				lock, err = state.AcquireWriter(dir)
			case "lifecycle":
				lock, err = state.AcquireScopedWriter(dir, "service-control")
			case "corrupt":
				err = os.MkdirAll(filepath.Join(dir, "keys"), 0700)
				if err == nil {
					err = os.WriteFile(filepath.Join(dir, "keys", "signing.seed"), []byte("invalid seed"), 0600)
				}
			}
			if err != nil {
				t.Fatal(err)
			}
			if lock != nil {
				defer lock.Release()
			}
			if err := cmdServicePrepare(nil, io.Discard); err == nil {
				t.Fatal("unsafe first identity accepted")
			}
			seed, err := os.ReadFile(filepath.Join(dir, "keys", "signing.seed"))
			if kind == "corrupt" {
				if err != nil || string(seed) != "invalid seed" {
					t.Fatal("corrupt key overwritten")
				}
			} else if !os.IsNotExist(err) {
				t.Fatal("rejected preparation created identity")
			}
			units, err := filepath.Glob(filepath.Join(dir, "*.service"))
			if err != nil || len(units) != 0 {
				t.Fatal("rejected preparation published unit")
			}
		})
	}
}
