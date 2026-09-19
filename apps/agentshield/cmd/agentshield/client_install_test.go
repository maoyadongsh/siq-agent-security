package main

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
	"testing"
)

func TestClientInstallRequiresConfirmationAndTrustedRelease(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	fixture := "../../testdata/contracts/skill-manifest.v2.sample.json"
	if _, err := os.ReadFile(fixture); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{nil, {"--manifest", fixture, "--binary", fixture}, {"--confirm-install", "--manifest", fixture, "--binary", fixture, "--port", "0"}, {"--confirm-install", "--manifest", fixture, "--binary", fixture}} {
		if err := cmdClientInstall(args, io.Discard); err == nil {
			t.Fatal("invalid/untrusted install accepted")
		}
		if _, err := os.Lstat(dir); !os.IsNotExist(err) {
			t.Fatal("invalid install created state")
		}
	}
}
func TestClientInstallationValidatesBeforeAndAfterStaging(t *testing.T) {
	for _, failure := range []string{"", "source", "stage", "target", "version", "location", "digest"} {
		t.Run(failure, func(t *testing.T) {
			dir := t.TempDir()
			raw := []byte("synthetic program")
			digest := fmt.Sprintf("%x", sha256.Sum256(raw))
			expected := filepath.Join(dir, "client-releases", digest, "siq-agent-security")
			calls, stages := 0, 0
			check := func(_ string, path string) (string, error) {
				calls++
				if (failure == "source" && calls == 1) || (failure == "target" && calls == 2) {
					return "", errors.New("verification refused")
				}
				if calls == 2 && path != expected && failure != "location" {
					t.Fatal("checked wrong target")
				}
				if failure == "version" && calls == 2 {
					return "changed", nil
				}
				return "test", nil
			}
			stage := func(string, string, string) (string, error) {
				stages++
				if failure == "stage" {
					return "", errors.New("stage failed")
				}
				path := expected
				if failure == "location" {
					path = filepath.Join(dir, "elsewhere")
				}
				if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
					t.Fatal(err)
				}
				content := raw
				if failure == "digest" {
					content = []byte("different")
				}
				if err := os.WriteFile(path, content, 0700); err != nil {
					t.Fatal(err)
				}
				return path, nil
			}
			path, version, err := prepareClientInstallation(dir, "manifest", "download", check, stage)
			if failure == "" {
				if err != nil || path != expected || version != "test" || calls != 2 || stages != 1 {
					t.Fatal("preparation failed", err)
				}
			} else if err == nil {
				t.Fatal("invalid preparation accepted")
			}
			if failure == "source" && stages != 0 {
				t.Fatal("staged before verification")
			}
		})
	}
}
func TestInstallationEnvironmentPinsStateDirectory(t *testing.T) {
	got := installationEnvironment([]string{"PATH=/test", "AGENTSHIELD_STATE_DIR=/legacy", "SIQ_AGENT_SECURITY_STATE_DIR=/other", "DISPLAY=:1"}, "/selected")
	want := []string{"PATH=/test", "DISPLAY=:1", "SIQ_AGENT_SECURITY_STATE_DIR=/selected"}
	if !reflect.DeepEqual(got, want) {
		t.Fatal("child inherited conflicting state directory", got)
	}
}

func TestClientInstallationBootstrapsIdentityAfterTrustBeforeStaging(t *testing.T) {
	for _, tc := range []struct {
		name       string
		trustError bool
		history    bool
	}{
		{name: "fresh"},
		{name: "untrusted", trustError: true},
		{name: "missing_historical_identity", history: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv(signing.SeedEnv, "")
			dir := t.TempDir()
			if tc.history {
				if err := os.WriteFile(filepath.Join(dir, "service.json"), []byte("history"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			checked, bootstrapped, staged := 0, 0, 0
			check := func(_, _ string) (string, error) {
				checked++
				if tc.trustError {
					return "", errors.New("untrusted")
				}
				return "v1", nil
			}
			bootstrap := func() error {
				bootstrapped++
				_, err := signing.Load(dir)
				return err
			}
			stage := func(_, _, _ string) (string, error) {
				staged++
				if _, err := os.Stat(filepath.Join(dir, "keys", "signing.seed")); err != nil {
					t.Fatal("staging preceded durable identity", err)
				}
				return "", errors.New("staging stopped after identity assertion")
			}
			_, _, err := prepareClientInstallationWithBootstrap(dir, "manifest", "binary", check, bootstrap, stage)
			if err == nil {
				t.Fatal("expected fixture stop or refusal")
			}
			if tc.trustError {
				if checked != 1 || bootstrapped != 0 || staged != 0 {
					t.Fatalf("untrusted source reached bootstrap/stage: %d/%d/%d", checked, bootstrapped, staged)
				}
			} else if tc.history {
				if checked != 1 || bootstrapped != 1 || staged != 0 || !errors.Is(err, signing.ErrIdentityMissing) {
					t.Fatalf("missing historical key accepted: %d/%d/%d %v", checked, bootstrapped, staged, err)
				}
			} else if checked != 1 || bootstrapped != 1 || staged != 1 {
				t.Fatalf("fresh bootstrap order: %d/%d/%d", checked, bootstrapped, staged)
			}
		})
	}
}

func TestClientInstallRejectsTransientSigningIdentity(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "new-state")
	t.Setenv(product.EnvSigningSeedOld, "")
	t.Setenv(product.EnvSigningSeed, "not-a-durable-seed")
	if err := bootstrapClientIdentity(dir); err == nil {
		t.Fatal("temporary installer identity accepted for a background service")
	}
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatal("transient identity changed state")
	}
}
