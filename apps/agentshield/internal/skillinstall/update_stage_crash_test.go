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

type updateStageCrashFixture struct {
	crashFixture
	UpdateID string
	Request  UpdateStageRequest
}

func TestUpdateStageCrashHelper(t *testing.T) {
	output := os.Getenv("SIQ_UPDATE_STAGE_CRASH_FIXTURE")
	if output == "" {
		return
	}
	f, op, req := readyUpdate(t)
	p, err := f.store.inspectUpdate(context.Background(), op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	d := updateStageCrashFixture{crashFixture{f.store.authority.Dir, f.root, f.request.InstanceID, op.InstallID}, p.UpdateID, req}
	raw, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(output, raw, 0600); err != nil {
		t.Fatal(err)
	}
	phase := os.Getenv("SIQ_UPDATE_STAGE_CRASH_PHASE")
	f.store.boundary = func(current string) error {
		if current == phase {
			os.Exit(77)
		}
		return nil
	}
	if _, _, err := f.store.StageUpdate(nil, op.InstallID, req); err != nil {
		t.Fatal(err)
	}
	t.Fatal("crash boundary not reached")
}
func TestUpdatePreparationProcessCrash(t *testing.T) {
	for _, phase := range []string{"update_copied", "update_plan_published"} {
		t.Run(phase, func(t *testing.T) {
			root := t.TempDir()
			childTemp := filepath.Join(root, "temporary")
			if err := os.Mkdir(childTemp, 0700); err != nil {
				t.Fatal(err)
			}
			descriptor := filepath.Join(root, "fixture.json")
			command := exec.Command(os.Args[0], "-test.run=^TestUpdateStageCrashHelper$")
			command.Env = append(os.Environ(), "TMPDIR="+childTemp, "TEMP="+childTemp, "TMP="+childTemp, "SIQ_UPDATE_STAGE_CRASH_FIXTURE="+descriptor, "SIQ_UPDATE_STAGE_CRASH_PHASE="+phase)
			output, err := command.CombinedOutput()
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 77 {
				t.Fatalf("child did not crash as intended: %v %s", err, output)
			}
			var d updateStageCrashFixture
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
			record, _, err := s.historicalRecord(context.Background(), d.InstallID)
			if err != nil {
				t.Fatal(err)
			}
			g, _, err := st.GetGrantWithSeq(record.Plan.GrantID)
			if err != nil || g.Status != "approved" {
				t.Fatal("crash revoked old permission", err)
			}
			if _, err := s.ReadOperation(nil, d.InstallID); err != nil {
				t.Fatal("crash damaged old installation", err)
			}
			prepared := filepath.Join(s.updateStage(d.UpdateID), "payload", "SKILL.md")
			before, err := os.ReadFile(prepared)
			if err != nil {
				t.Fatal(err)
			}
			p, err := s.LoadUpdatePlan(nil, d.UpdateID)
			if phase == "update_copied" {
				if !errors.Is(err, ErrNotFound) {
					t.Fatal("orphan became ready", p, err)
				}
				if _, _, err := s.StageUpdate(nil, d.InstallID, d.Request); !errors.Is(err, ErrConflict) {
					t.Fatal("orphan was implicitly adopted", err)
				}
			} else {
				if err != nil {
					t.Fatal("published plan lost after crash", err)
				}
				again, reused, err := s.StageUpdate(nil, d.InstallID, d.Request)
				if err != nil || !reused || !sameDocument(p, again) {
					t.Fatal("published retry changed plan", err)
				}
			}
			if after, err := os.ReadFile(prepared); err != nil || string(before) != string(after) {
				t.Fatal("restart changed staged copy", err)
			}
		})
	}
}
