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

type updateTransactionCrashFixture struct {
	crashFixture
	UpdateID string
	Request  UpdateCommitRequest
}

func TestUpdateTransactionCrashHelper(t *testing.T) {
	output := os.Getenv("SIQ_UPDATE_TRANSACTION_CRASH_FIXTURE")
	if output == "" {
		return
	}
	f, p, req := confirmedUpdate(t)
	d := updateTransactionCrashFixture{crashFixture{f.store.authority.Dir, f.root, f.request.InstanceID, p.Record.InstallID}, p.UpdateID, req}
	raw, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(output, raw, 0600); err != nil {
		t.Fatal(err)
	}
	phase := os.Getenv("SIQ_UPDATE_TRANSACTION_CRASH_PHASE")
	f.store.boundary = func(current string) error {
		if current == phase {
			os.Exit(77)
		}
		return nil
	}
	if _, err := f.store.CommitUpdate(nil, req); err != nil {
		t.Fatal(err)
	}
	t.Fatal("crash boundary not reached")
}
func TestUpdateTransactionProcessCrash(t *testing.T) {
	for _, phase := range []string{"update_claim_published", "removal_claim_published", "update_previous_removed", "update_install_plan_published", "file_published:references/guide.md", "update_before_result"} {
		t.Run(phase, func(t *testing.T) {
			root := t.TempDir()
			childTemp := filepath.Join(root, "temporary")
			if err := os.Mkdir(childTemp, 0700); err != nil {
				t.Fatal(err)
			}
			descriptor := filepath.Join(root, "fixture.json")
			command := exec.Command(os.Args[0], "-test.run=^TestUpdateTransactionCrashHelper$")
			command.Env = append(os.Environ(), "TMPDIR="+childTemp, "TEMP="+childTemp, "TMP="+childTemp, "SIQ_UPDATE_TRANSACTION_CRASH_FIXTURE="+descriptor, "SIQ_UPDATE_TRANSACTION_CRASH_PHASE="+phase)
			output, err := command.CombinedOutput()
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 77 {
				t.Fatalf("child did not crash as intended: %v %s", err, output)
			}
			var d updateTransactionCrashFixture
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

			v, err := s.ReadUpdate(nil, d.UpdateID)
			if err != nil {
				t.Fatal(err)
			}
			if v.Result != nil {
				t.Fatal("crash fabricated final result")
			}
			if phase == "file_published:references/guide.md" {
				v, err = s.RecoverUpdate(nil, recoverUpdateRequest(v))
				if err != nil || v.Status != "aborted" {
					t.Fatal(v, err)
				}
			} else {
				v, err = s.CommitUpdate(nil, d.Request)
				if err != nil || v.Status != "updated_unverified" {
					t.Fatal(v, err)
				}
			}
			g, _, err := st.GetGrantWithSeq(v.Claim.Plan.Record.Plan.GrantID)
			if err != nil || g.Status != "revoked" {
				t.Fatal("old authority not withdrawn", err)
			}
			if v.Status == "updated_unverified" {
				if _, err := s.ReadOperation(nil, v.Installation.InstallID); err != nil {
					t.Fatal(err)
				}
			} else if _, err := os.Lstat(filepath.Join(d.Root, "skills", "example")); !os.IsNotExist(err) {
				t.Fatal("failed copy retained", err)
			}
		})
	}
}
