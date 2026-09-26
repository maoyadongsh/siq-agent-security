//go:build linux

package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

func TestPrepareInstallGates(t *testing.T) {
	raw, err := os.ReadFile("installplan/testdata/plan.json")
	if err != nil {
		t.Fatal(err)
	}
	h := sha256.Sum256(raw)
	now, _ := time.Parse(time.RFC3339, "2026-09-25T01:01:00Z")
	for _, scenario := range []string{"valid", "tenant", "environment", "origin", "arch", "expired", "unconfirmed", "changed_plan", "stage_failure", "production_publisher"} {
		t.Run(scenario, func(t *testing.T) {
			root := t.TempDir()
			planFile, releaseFile := filepath.Join(root, "plan.json"), filepath.Join(root, "release.json")
			if err := os.WriteFile(planFile, raw, 0600); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(releaseFile, []byte(`{"untrusted":true}`), 0600); err != nil {
				t.Fatal(err)
			}
			args := []string{"--plan", planFile, "--release", releaseFile, "--bundle", root, "--staging-parent", root, "--tenant", "tenant-fixture", "--environment", "env-fixture", "--control-plane", "https://security.example.test:8443", "--confirm-plan-sha256", hex.EncodeToString(h[:])}
			clock, arch := now, "arm64"
			change := func(flag, value string) {
				for i := range args {
					if args[i] == flag {
						args[i+1] = value
						return
					}
				}
				t.Fatal("missing flag")
			}
			switch scenario {
			case "tenant":
				change("--tenant", "other")
			case "environment":
				change("--environment", "other")
			case "origin":
				change("--control-plane", "https://other.test")
			case "arch":
				arch = "amd64"
			case "expired":
				clock = now.Add(time.Hour)
			case "unconfirmed":
				change("--confirm-plan-sha256", "")
			case "changed_plan":
				if err := os.WriteFile(planFile, append(append([]byte{}, raw...), '\n'), 0600); err != nil {
					t.Fatal(err)
				}
			}
			calls := 0
			stage := func(p installplan.Plan, manifest []byte, source, parent string) (string, error) {
				calls++
				if scenario == "stage_failure" {
					return "", installplan.ErrInvalid
				}
				if p.PlanID == "" || source != root || parent != root || len(manifest) == 0 {
					t.Fatal("invalid dependency inputs")
				}
				return filepath.Join(root, "stage-fixture"), nil
			}
			if scenario == "production_publisher" {
				stage = installplan.StageBundle
			}
			var output bytes.Buffer
			err := prepareInstall(args, &output, clock, arch, stage, installplan.VerifyStagedBundle)
			if scenario == "valid" {
				if err != nil || calls != 1 {
					t.Fatalf("valid plan: %v calls=%d", err, calls)
				}
				var result map[string]string
				if json.Unmarshal(output.Bytes(), &result) != nil || result["status"] != "staged_only" || result["plan_sha256"] != hex.EncodeToString(h[:]) {
					t.Fatal("invalid output")
				}
			} else {
				if err != errPrepareInstall || output.Len() != 0 {
					t.Fatal("unsafe plan accepted or error leaked")
				}
				if scenario != "stage_failure" && calls != 0 {
					t.Fatal("invalid plan reached stage writer")
				}
			}
		})
	}
}

func TestInstallDocumentRejectsUnsafeFiles(t *testing.T) {
	root := t.TempDir()
	file := filepath.Join(root, "file")
	if err := os.WriteFile(file, []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	link, fifo, large := filepath.Join(root, "link"), filepath.Join(root, "fifo"), filepath.Join(root, "large")
	if err := os.Symlink(file, link); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(fifo, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(large, []byte(strings.Repeat(" ", installplan.MaxBytes+1)), 0600); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{root, link, fifo, large, filepath.Join(root, "missing")} {
		if _, err := readInstallDocument(path); err != errPrepareInstall {
			t.Fatal("unsafe file accepted")
		}
	}
}

func TestPrepareHelpAndArgumentPrivacy(t *testing.T) {
	for _, args := range [][]string{{"--help"}, {"--unknown=secret-value"}, {"positional-secret"}} {
		var out bytes.Buffer
		err := prepareInstall(args, &out, time.Now(), "arm64", func(installplan.Plan, []byte, string, string) (string, error) {
			t.Fatal("unexpected stage")
			return "", nil
		}, installplan.VerifyStagedBundle)
		if args[0] == "--help" {
			if err != nil || out.Len() == 0 {
				t.Fatal("help failed")
			}
		} else if err != errPrepareInstall || out.Len() != 0 {
			t.Fatal("argument echoed or accepted")
		}
	}
}

func TestPrepareResumeDoesNotRestage(t *testing.T) {
	raw, err := os.ReadFile("installplan/testdata/plan.json")
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	planFile, releaseFile := filepath.Join(root, "plan"), filepath.Join(root, "release")
	if os.WriteFile(planFile, raw, 0600) != nil || os.WriteFile(releaseFile, []byte("fixture"), 0600) != nil {
		t.Fatal("fixture write")
	}
	h := sha256.Sum256(raw)
	now, _ := time.Parse(time.RFC3339, "2026-09-25T01:01:00Z")
	for _, scenario := range []string{"valid", "expired", "mixed", "invalid_stage"} {
		t.Run(scenario, func(t *testing.T) {
			args := []string{"--plan", planFile, "--release", releaseFile, "--resume-stage", root, "--tenant", "tenant-fixture", "--environment", "env-fixture", "--control-plane", "https://security.example.test:8443", "--confirm-plan-sha256", hex.EncodeToString(h[:])}
			clock := now
			if scenario == "expired" {
				clock = now.Add(time.Hour)
			}
			if scenario == "mixed" {
				args = append(args, "--bundle", root)
			}
			calls := 0
			var out bytes.Buffer
			err := prepareInstall(args, &out, clock, "arm64", func(installplan.Plan, []byte, string, string) (string, error) {
				t.Fatal("resume attempted a write")
				return "", nil
			}, func(p installplan.Plan, manifest []byte, path string) error {
				calls++
				if path != root || p.PlanID == "" || string(manifest) != "fixture" {
					t.Fatal("wrong recovery inputs")
				}
				if scenario == "invalid_stage" {
					return installplan.ErrInvalid
				}
				return nil
			})
			if scenario == "valid" {
				if err != nil || calls != 1 || !strings.Contains(out.String(), "staged_only") {
					t.Fatal("resume failed")
				}
			} else {
				if err != errPrepareInstall || out.Len() != 0 {
					t.Fatal("invalid resume accepted")
				}
				if scenario != "invalid_stage" && calls != 0 {
					t.Fatal("invalid context reached recovery")
				}
			}
		})
	}
}
