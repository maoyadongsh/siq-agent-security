//go:build windows

package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func windowsClientInstallBootstrapDir(t *testing.T, initialized bool) string {
	t.Helper()
	t.Setenv(product.EnvSigningSeed, "")
	t.Setenv(product.EnvSigningSeedOld, "")
	dir := filepath.Join(t.TempDir(), "s")
	t.Setenv(product.EnvStateDir, dir)
	if initialized {
		if err := cmdInitialize(nil, io.Discard); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

func windowsClientInstallTrustedFixture(string, string) (string, error) {
	return "synthetic-verified-release", nil
}

// Only the release checker and staging operation are injected. The key,
// writers, staged bytes, init and registration identity load are real. This
// synthetic program is never executed and no system task is registered.
func windowsClientInstallBootstrapStage(t *testing.T, dir string) func(string, string, string) (string, error) {
	t.Helper()
	return func(gotDir, _, _ string) (string, error) {
		if gotDir != dir {
			t.Fatal("staging changed state directory")
		}
		if _, err := signing.LoadExisting(dir); err != nil {
			t.Fatalf("staging reached before the initial disk identity exists: %v", err)
		}
		writer, err := state.AcquireWriter(dir)
		if err != nil {
			t.Fatalf("bootstrap retained the primary writer across staging: %v", err)
		}
		if err := writer.Release(); err != nil {
			t.Fatal(err)
		}
		return windowsClientInstallStagedFixture(t, dir)
	}
}

func windowsClientInstallStagedFixture(t *testing.T, dir string) (string, error) {
	t.Helper()
	writer, err := state.AcquireScopedWriter(dir, "client-releases")
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		if err := writer.Release(); err != nil {
			t.Error(err)
		}
	}()
	raw := []byte("synthetic Windows client; never execute")
	digest := fmt.Sprintf("%x", sha256.Sum256(raw))
	path := filepath.Join(dir, "client-releases", digest, "siq-agent-security.exe")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return "", err
	}
	if err := os.WriteFile(path, raw, 0700); err != nil {
		return "", err
	}
	return path, nil
}

func TestWindowsClientInstallBootstrapsIdentityBeforeStaging(t *testing.T) {
	for _, initialized := range []bool{false, true} {
		name := "absent-state"
		if initialized {
			name = "initialized-without-key"
		}
		t.Run(name, func(t *testing.T) {
			dir := windowsClientInstallBootstrapDir(t, initialized)
			stage := windowsClientInstallBootstrapStage(t, dir)
			if _, _, err := prepareClientInstallation(dir, "manifest", "download", windowsClientInstallTrustedFixture, stage); err != nil {
				t.Fatal(err)
			}
			before, err := signing.LoadExisting(dir)
			if err != nil {
				t.Fatal(err)
			}
			// These are the real init and identity operations reached by setup
			// and task-register after client-releases already contains files.
			if err := cmdInitialize(nil, io.Discard); err != nil {
				t.Fatal(err)
			}
			after, err := loadWindowsTaskPreparationKey(dir)
			if err != nil || !bytes.Equal(before.Public(), after.Public()) {
				t.Fatal("staged install stranded or replaced the registration identity", err)
			}
			if _, _, err := prepareClientInstallation(dir, "manifest", "download", windowsClientInstallTrustedFixture, stage); err != nil {
				t.Fatal("repeat preparation failed", err)
			}
			after, err = signing.LoadExisting(dir)
			if err != nil || !bytes.Equal(before.Public(), after.Public()) {
				t.Fatal("repeat preparation replaced the identity", err)
			}
		})
	}
}

func TestWindowsClientInstallUntrustedReleaseDoesNotBootstrap(t *testing.T) {
	dir := windowsClientInstallBootstrapDir(t, false)
	refused := errors.New("untrusted release fixture")
	check := func(string, string) (string, error) { return "", refused }
	stage := func(string, string, string) (string, error) {
		t.Fatal("untrusted release entered staging")
		return "", nil
	}
	if _, _, err := prepareClientInstallation(dir, "manifest", "download", check, stage); !errors.Is(err, refused) {
		t.Fatal("release refusal lost", err)
	}
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatal("untrusted release created state or identity", err)
	}
}

func TestWindowsClientInstallMissingHistoricalIdentityRefusesBeforeStaging(t *testing.T) {
	for _, history := range []string{"evidence/proof.signature", "client-releases/old/program.exe"} {
		t.Run(history, func(t *testing.T) {
			dir := windowsClientInstallBootstrapDir(t, true)
			key, err := loadWindowsTaskPreparationKey(dir)
			if err != nil {
				t.Fatal(err)
			}
			proof := []byte("existing installation history")
			raw := []byte(key.SignBytes(proof))
			path := filepath.Join(dir, filepath.FromSlash(history))
			if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			seed := filepath.Join(dir, "keys", "signing.seed")
			if err := os.Remove(seed); err != nil {
				t.Fatal(err)
			}
			stage := func(string, string, string) (string, error) {
				t.Fatal("historical missing key reached staging")
				return "", nil
			}
			if _, _, err := prepareClientInstallation(dir, "manifest", "download", windowsClientInstallTrustedFixture, stage); !errors.Is(err, signing.ErrIdentityMissing) {
				t.Fatal("history no longer requires restoration", err)
			}
			if _, err := os.Lstat(seed); !os.IsNotExist(err) {
				t.Fatal("historical missing key was recreated", err)
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(raw, after) || !signing.VerifyBytes(key.Public(), proof, string(after)) {
				t.Fatal("existing history changed", err)
			}
		})
	}
}

func TestWindowsClientInstallBootstrapFailureDoesNotStageOrReplaceKey(t *testing.T) {
	for _, scenario := range []string{"corrupt-key", "key-acl", "future-writer"} {
		t.Run(scenario, func(t *testing.T) {
			dir := windowsClientInstallBootstrapDir(t, true)
			if _, err := loadWindowsTaskPreparationKey(dir); err != nil {
				t.Fatal(err)
			}
			seed := filepath.Join(dir, "keys", "signing.seed")
			switch scenario {
			case "corrupt-key":
				if err := os.WriteFile(seed, []byte("invalid-owned-seed"), 0600); err != nil {
					t.Fatal(err)
				}
			case "key-acl":
				acltest.BroadenRead(t, dir, seed)
			case "future-writer":
				marker, err := stateformat.ReadMarker(dir)
				if err != nil || marker.Schema != "state-format/v2" {
					t.Fatal("expected initialized versioned state", err)
				}
				marker.MinWriter = stateformat.WriterVersion + 1
				raw, err := json.Marshal(marker)
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(dir, stateformat.MarkerName), raw, 0600); err != nil {
					t.Fatal(err)
				}
			}
			before, err := os.ReadFile(seed)
			if err != nil {
				t.Fatal(err)
			}
			stage := func(string, string, string) (string, error) {
				t.Fatal("failed bootstrap reached staging")
				return "", nil
			}
			if _, _, err := prepareClientInstallation(dir, "manifest", "download", windowsClientInstallTrustedFixture, stage); err == nil {
				t.Fatal("failed bootstrap accepted")
			} else if scenario == "future-writer" && !errors.Is(err, state.ErrFutureState) {
				t.Fatal("future writer barrier changed classification", err)
			}
			after, err := os.ReadFile(seed)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("failed bootstrap changed the key", err)
			}
			if _, err := os.Lstat(filepath.Join(dir, "client-releases")); !os.IsNotExist(err) {
				t.Fatal("failed bootstrap created installation history", err)
			}
		})
	}
}

func TestWindowsClientInstallReusesIdentityWhilePrimaryWriterHeld(t *testing.T) {
	dir := windowsClientInstallBootstrapDir(t, true)
	if _, err := loadWindowsTaskPreparationKey(dir); err != nil {
		t.Fatal(err)
	}
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := writer.Release(); err != nil {
			t.Error(err)
		}
	})
	seed := filepath.Join(dir, "keys", "signing.seed")
	before, err := os.ReadFile(seed)
	if err != nil {
		t.Fatal(err)
	}
	lock := filepath.Join(dir, state.LockFile)
	lockBefore, err := os.ReadFile(lock)
	if err != nil {
		t.Fatal(err)
	}
	stages := 0
	stage := func(gotDir, _, _ string) (string, error) {
		if gotDir != dir {
			t.Fatal("staging changed state directory")
		}
		stages++
		if _, err := signing.LoadExisting(dir); err != nil {
			t.Fatal("existing identity unavailable during staging", err)
		}
		if probe, err := state.AcquireWriter(dir); !errors.Is(err, state.ErrWriterBusy) {
			if probe != nil {
				_ = probe.Release()
			}
			t.Fatal("preparation removed or replaced the running instance writer", err)
		}
		return windowsClientInstallStagedFixture(t, dir)
	}
	for attempt := 0; attempt < 2; attempt++ {
		if _, _, err := prepareClientInstallation(dir, "manifest", "download", windowsClientInstallTrustedFixture, stage); err != nil {
			t.Fatal("valid existing identity could not reuse the running instance", err)
		}
	}
	after, err := os.ReadFile(seed)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("repeated preparation changed the identity", err)
	}
	lockAfter, err := os.ReadFile(lock)
	if err != nil || !bytes.Equal(lockBefore, lockAfter) || stages != 2 {
		t.Fatal("repeated preparation changed the running writer or skipped staging", err)
	}
}

func TestWindowsClientInstallMissingIdentityWithPrimaryWriterHeldRefuses(t *testing.T) {
	dir := windowsClientInstallBootstrapDir(t, true)
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := writer.Release(); err != nil {
			t.Error(err)
		}
	})
	stage := func(string, string, string) (string, error) {
		t.Fatal("missing identity bypassed the held primary writer")
		return "", nil
	}
	if _, _, err := prepareClientInstallation(dir, "manifest", "download", windowsClientInstallTrustedFixture, stage); !errors.Is(err, state.ErrWriterBusy) {
		t.Fatal("missing identity did not require the primary writer", err)
	}
	if _, err := os.Lstat(filepath.Join(dir, "keys", "signing.seed")); !os.IsNotExist(err) {
		t.Fatal("missing identity was created despite the held writer", err)
	}
	if _, err := os.Lstat(filepath.Join(dir, "client-releases")); !os.IsNotExist(err) {
		t.Fatal("writer conflict created installation history", err)
	}
	if held, _, err := state.WriterHeld(dir); err != nil || !held {
		t.Fatal("failed preparation released the existing writer", err)
	}
}

func TestWindowsClientInstallStageFailureRetainsIdentityForRetry(t *testing.T) {
	dir := windowsClientInstallBootstrapDir(t, false)
	refused := errors.New("staging failure fixture")
	stage := func(string, string, string) (string, error) { return "", refused }
	if _, _, err := prepareClientInstallation(dir, "manifest", "download", windowsClientInstallTrustedFixture, stage); !errors.Is(err, refused) {
		t.Fatal("staging failure lost", err)
	}
	before, err := signing.LoadExisting(dir)
	if err != nil {
		t.Fatal("failed staging lost the initialized identity", err)
	}
	if _, _, err := prepareClientInstallation(dir, "manifest", "download", windowsClientInstallTrustedFixture, windowsClientInstallBootstrapStage(t, dir)); err != nil {
		t.Fatal("retry failed", err)
	}
	after, err := signing.LoadExisting(dir)
	if err != nil || !bytes.Equal(before.Public(), after.Public()) {
		t.Fatal("retry replaced the initialized identity", err)
	}
}
