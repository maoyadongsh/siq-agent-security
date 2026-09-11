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

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

type removalCrashFixture struct {
	crashFixture
	Request RemoveRequest
}

func TestRemovalCrashHelper(t *testing.T) {
	output := os.Getenv("SIQ_REMOVAL_CRASH_FIXTURE")
	if output == "" {
		return
	}
	f, op, activation := readyActivation(t)
	if _, err := f.store.Activate(nil, op.InstallID, activation); err != nil {
		t.Fatal(err)
	}
	req := removalRequest(t, f.store, op.InstallID)
	d := removalCrashFixture{crashFixture{f.store.authority.Dir, f.root, f.request.InstanceID, op.InstallID}, req}
	raw, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(output, raw, 0600); err != nil {
		t.Fatal(err)
	}
	phase := os.Getenv("SIQ_REMOVAL_CRASH_PHASE")
	f.store.boundary = func(current string) error {
		if current == phase {
			os.Exit(77)
		}
		return nil
	}
	if _, err := f.store.Remove(nil, op.InstallID, req); err != nil {
		t.Fatal(err)
	}
	t.Fatal("crash boundary not reached")
}

func TestRemovalProcessCrashRecovery(t *testing.T) {
	for _, phase := range []string{"removal_claim_published", "removal_authority_ready", "removal_file_removed:SKILL.md", "removal_owner_removed:", "removal_before_result"} {
		t.Run(phase, func(t *testing.T) {
			root := t.TempDir()
			childTemp := filepath.Join(root, "temporary")
			if err := os.Mkdir(childTemp, 0700); err != nil {
				t.Fatal(err)
			}
			descriptor := filepath.Join(root, "fixture.json")
			command := exec.Command(os.Args[0], "-test.run=^TestRemovalCrashHelper$")
			command.Env = append(os.Environ(), "TMPDIR="+childTemp, "TEMP="+childTemp, "TMP="+childTemp, "SIQ_REMOVAL_CRASH_FIXTURE="+descriptor, "SIQ_REMOVAL_CRASH_PHASE="+phase)
			output, err := command.CombinedOutput()
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 77 {
				t.Fatalf("child did not crash at intended boundary: %v %s", err, output)
			}
			var d removalCrashFixture
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
			view, err := s.ReadRemoval(nil, d.InstallID)
			if err != nil || view.Claim == nil || view.Result != nil {
				t.Fatal("lost pending operation after restart", view, err)
			}
			wantStatus := "cleanup_pending"
			if phase == "removal_claim_published" {
				wantStatus = "revocation_pending"
			} else if view.Grant.Status != "revoked" || !grant.Verify(key.Public(), *view.Grant) {
				t.Fatal("cleanup reached before signed revocation")
			}
			if view.Status != wantStatus {
				t.Fatal("wrong pending status", view.Status)
			}
			if err := s.ValidateRuntimeGrant(nil, view.Grant); err == nil {
				t.Fatal("pending removal retained runtime authority after restart")
			}
			if err := s.removalStarted(d.InstallID); !errors.Is(err, ErrRemovalPending) {
				t.Fatal("pending removal can be reactivated", err)
			}
			target := filepath.Join(d.Root, "skills", "example")
			result, err := s.Remove(nil, d.InstallID, d.Request)
			if phase == "removal_owner_removed:" {
				if !errors.Is(err, ErrRecoveryRequired) || result == nil || result.Status != "cleanup_pending" {
					t.Fatal("unmarked directory was guessed to be owned", result, err)
				}
				entries, readErr := os.ReadDir(target)
				if readErr != nil || len(entries) != 0 {
					t.Fatal("unmarked empty directory changed", readErr)
				}
				// Simulate the user inspecting and removing their empty fixture directory.
				if err := os.Remove(target); err != nil {
					t.Fatal(err)
				}
				result, err = s.Remove(nil, d.InstallID, d.Request)
			}
			if err != nil || result == nil || result.Status != "removed" || !result.Result.GrantRevoked {
				t.Fatal("restart recovery failed", result, err)
			}
			if _, err := os.Lstat(target); !os.IsNotExist(err) {
				t.Fatal("owned target retained", err)
			}
		})
	}
}
