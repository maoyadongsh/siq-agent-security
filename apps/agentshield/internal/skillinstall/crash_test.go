package skillinstall

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

type crashFixture struct{ State, Root, Instance, InstallID string }

func TestInstallationCrashHelper(t *testing.T) {
	output := os.Getenv("SIQ_INSTALL_CRASH_FIXTURE")
	if output == "" {
		return
	}
	f, p, request := readyInstall(t)
	raw, err := json.Marshal(crashFixture{f.store.authority.Dir, f.root, p.InstanceID, installID(p.PlanID)})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(output, raw, 0600); err != nil {
		t.Fatal(err)
	}
	phase := os.Getenv("SIQ_INSTALL_CRASH_PHASE")
	f.store.boundary = func(current string) error {
		if current == phase {
			os.Exit(77)
		}
		return nil
	}
	if _, err := f.store.Apply(nil, request); err != nil {
		t.Fatal(err)
	}
	t.Fatal("crash boundary not reached")
}
func TestInstallationProcessCrashRecovery(t *testing.T) {
	for _, phase := range []string{"spooled", "directory_created:", "file_published:skill-manifest.json", "before_result"} {
		t.Run(phase, func(t *testing.T) {
			root := t.TempDir()
			childTemp := filepath.Join(root, "temporary")
			if err := os.Mkdir(childTemp, 0700); err != nil {
				t.Fatal(err)
			}
			descriptor := filepath.Join(root, "fixture.json")
			command := exec.Command(os.Args[0], "-test.run=^TestInstallationCrashHelper$")
			command.Env = append(os.Environ(), "TMPDIR="+childTemp, "TEMP="+childTemp, "TMP="+childTemp, "SIQ_INSTALL_CRASH_FIXTURE="+descriptor, "SIQ_INSTALL_CRASH_PHASE="+phase)
			output, err := command.CombinedOutput()
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 77 {
				t.Fatalf("child did not crash at intended boundary: %v %s", err, output)
			}
			var d crashFixture
			raw, err := os.ReadFile(descriptor)
			if err != nil || json.Unmarshal(raw, &d) != nil {
				t.Fatal("missing crash descriptor", err)
			}
			st, err := state.Open(d.State)
			if err != nil {
				t.Fatal(err)
			}
			key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
			if err != nil {
				t.Fatal(err)
			}
			pack, err := rulepack.Builtin()
			if err != nil {
				t.Fatal(err)
			}
			imports, err := skillimport.Open(d.State, key, pack, "fixture")
			if err != nil {
				t.Fatal(err)
			}
			s, err := Open(st, key, imports, func(context.Context, string) (Target, error) {
				return Target{d.Instance, "hermes", d.Root, "Hermes work"}, nil
			})
			if err != nil {
				t.Fatal(err)
			}
			if _, err := s.ReadOperation(nil, d.InstallID); !errors.Is(err, ErrRecoveryRequired) {
				t.Fatal("incomplete operation not identified", err)
			}
			result, err := s.Recover(nil, d.InstallID, "recovery-human")
			destination := filepath.Join(d.Root, "skills", "example")
			if phase == "directory_created:" {
				if !errors.Is(err, ErrRecoveryRequired) {
					t.Fatal("unowned crash directory removed", result, err)
				}
				entries, err := os.ReadDir(destination)
				if err != nil || len(entries) != 0 {
					t.Fatal("unknown directory changed", err)
				}
			} else {
				if err != nil || result.Status != "rolled_back" {
					t.Fatal("restart recovery failed", result, err)
				}
				if _, err := os.Stat(destination); !os.IsNotExist(err) {
					t.Fatal("owned destination retained", err)
				}
			}
		})
	}
}
