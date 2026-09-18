package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

func TestWindowsProfileCommandConfirmationBeforeStateAccess(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "missing-state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	for _, args := range [][]string{nil, {"--confirm=false"}, {"--confirm", "unexpected"}, {"--unknown"}} {
		var out bytes.Buffer
		if err := cmdStateEnableWindowsResources(args, &out); err == nil {
			t.Fatal("invalid confirmation accepted")
		}
		if _, err := os.Lstat(dir); !os.IsNotExist(err) {
			t.Fatal("unconfirmed access created state", err)
		}
	}
}

func windowsProfileCommandIdentityFixture(t *testing.T) string {
	t.Helper()
	if runtime.GOOS != "windows" {
		t.Skip("native Windows activation only")
	}
	t.Setenv(product.EnvSigningSeed, "")
	t.Setenv(product.EnvSigningSeedOld, "")
	dir := filepath.Join(t.TempDir(), "state")
	t.Setenv(product.EnvStateDir, dir)
	if err := cmdInitialize(nil, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	return dir
}

func writeWindowsProfileIdentityFixture(path string, raw []byte) error {
	f, err := statefs.CreatePrivate(path)
	if err != nil {
		return err
	}
	_, err = f.Write(raw)
	return errors.Join(err, f.Sync(), f.Close())
}

func TestWindowsProfileCommandBootstrapsIdentityBeforeJournal(t *testing.T) {
	dir := windowsProfileCommandIdentityFixture(t)
	if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	// This is the identity load reached by serve after the exact normal CLI
	// order. The old command first published history and stranded this load.
	key, err := signing.Load(dir)
	if err != nil {
		t.Fatalf("init -> confirmed activation stranded the first serve identity: %v", err)
	}
	before := append([]byte(nil), key.Public()...)
	if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	after, err := signing.LoadExisting(dir)
	if err != nil || !bytes.Equal(before, after.Public()) {
		t.Fatal("activation retry changed signing identity", err)
	}
}

func TestWindowsProfileCommandPreservesMissingHistoricalIdentity(t *testing.T) {
	dir := windowsProfileCommandIdentityFixture(t)
	key, err := signing.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	proof := []byte("owned historical identity proof")
	signature := []byte(key.SignBytes(proof))
	history := filepath.Join(dir, "evidence", "identity-proof.signature")
	if err := writeWindowsProfileIdentityFixture(history, signature); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(dir, "keys", "signing.seed")); err != nil {
		t.Fatal(err)
	}
	marker, err := os.ReadFile(filepath.Join(dir, stateformat.MarkerName))
	if err != nil {
		t.Fatal(err)
	}
	if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &bytes.Buffer{}); !errors.Is(err, signing.ErrIdentityMissing) {
		t.Fatal("historical missing key did not require restoration", err)
	}
	if _, err := os.Lstat(filepath.Join(dir, "keys", "signing.seed")); !os.IsNotExist(err) {
		t.Fatal("missing historical identity was recreated", err)
	}
	if _, err := os.Lstat(filepath.Join(dir, stateformat.WindowsProfileDir)); !os.IsNotExist(err) {
		t.Fatal("refused historical identity published profile history", err)
	}
	current, err := os.ReadFile(filepath.Join(dir, stateformat.MarkerName))
	if err != nil || !bytes.Equal(marker, current) {
		t.Fatal("refused identity changed marker", err)
	}
	current, err = os.ReadFile(history)
	if err != nil || !bytes.Equal(signature, current) || !signing.VerifyBytes(key.Public(), proof, string(current)) {
		t.Fatal("historical proof changed", err)
	}
}

func TestWindowsProfileCommandDoesNotReplaceCorruptIdentity(t *testing.T) {
	dir := windowsProfileCommandIdentityFixture(t)
	if _, err := signing.Load(dir); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "keys", "signing.seed")
	corrupt := []byte("invalid-owned-test-seed")
	if err := os.WriteFile(path, corrupt, 0600); err != nil {
		t.Fatal(err)
	}
	if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &bytes.Buffer{}); err == nil {
		t.Fatal("corrupt identity accepted")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(corrupt, after) {
		t.Fatal("corrupt identity overwritten", err)
	}
	if _, err := os.Lstat(filepath.Join(dir, stateformat.WindowsProfileDir)); !os.IsNotExist(err) {
		t.Fatal("corrupt identity published profile history", err)
	}
}

func TestWindowsProfileCommandRecoveryDoesNotReadAcrossActiveBarrier(t *testing.T) {
	for _, missingKey := range []bool{false, true} {
		name := "identity-retained"
		if missingKey {
			name = "identity-missing"
		}
		t.Run(name, func(t *testing.T) {
			dir := windowsProfileCommandIdentityFixture(t)
			key, err := signing.Load(dir)
			if err != nil {
				t.Fatal(err)
			}
			if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &bytes.Buffer{}); err != nil {
				t.Fatal(err)
			}
			plan, err := os.ReadFile(filepath.Join(dir, stateformat.WindowsProfileDir, "plan.json"))
			if err != nil {
				t.Fatal(err)
			}
			if missingKey {
				if err := os.Remove(filepath.Join(dir, "keys", "signing.seed")); err != nil {
					t.Fatal(err)
				}
			}
			// Reproduce the durable state just before removal of the active
			// barrier; no migration internals or runtime fault switch are used.
			if err := writeWindowsProfileIdentityFixture(filepath.Join(dir, stateformat.PlanName), plan); err != nil {
				t.Fatal(err)
			}
			if _, err := signing.Load(dir); !errors.Is(err, stateformat.ErrWindowsProfileMigration) {
				t.Fatal("ordinary identity load bypassed active barrier", err)
			}
			if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &bytes.Buffer{}); err != nil {
				t.Fatal("explicit recovery was blocked by identity bootstrap", err)
			}
			if err := stateformat.RequireWindowsProfile(dir); err != nil {
				t.Fatal("recovery incomplete", err)
			}
			after, err := signing.Load(dir)
			if missingKey {
				if !errors.Is(err, signing.ErrIdentityMissing) {
					t.Fatal("recovery created a replacement historical identity", err)
				}
			} else if err != nil || !bytes.Equal(key.Public(), after.Public()) {
				t.Fatal("recovery changed original identity", err)
			}
		})
	}
}

func TestWindowsProfileCommandContractAndRetry(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("native Windows activation only")
	}
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", filepath.Join(t.TempDir(), "state"))
	var out bytes.Buffer
	if err := cmdInitialize(nil, &out); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &out); err != nil {
		t.Fatal(err)
	}
	fixture, err := os.ReadFile("../../testdata/contracts/local-state-windows-profile-result.json")
	var got, expected map[string]any
	if err != nil || json.Unmarshal(out.Bytes(), &got) != nil || json.Unmarshal(fixture, &expected) != nil || !reflect.DeepEqual(got, expected) {
		t.Fatal("activation result contract differs", err)
	}
	out.Reset()
	if err := cmdStateEnableWindowsResources([]string{"--confirm"}, &out); err != nil {
		t.Fatal(err)
	}
	if json.Unmarshal(out.Bytes(), &got) != nil || got["status"] != "up_to_date" {
		t.Fatal("retry result")
	}
}
