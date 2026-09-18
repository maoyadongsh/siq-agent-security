package state

import (
	"bytes"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func windowsProfileFixture(t *testing.T) *Store {
	t.Helper()
	s, w := initializationStore(t)
	if _, err := s.Initialize(w, 49123); err != nil {
		t.Fatal(err)
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
	return s
}

func assertProfileHistoryUnchanged(t *testing.T, dir string, before map[string]string) {
	t.Helper()
	after := treeSnapshot(t, dir)
	for name, value := range before {
		if name == stateformat.MarkerName {
			continue
		}
		if after[name] != value {
			t.Fatal("previous history changed", name)
		}
	}
}

func TestWindowsProfileActivationRetainsMigratedHistory(t *testing.T) {
	s := migrationFixture(t)
	if _, err := s.MigrateState("legacy-migration"); err != nil {
		t.Fatal(err)
	}
	before := treeSnapshot(t, s.Dir)
	if status, err := s.ActivateWindowsProfile(true, "profile-test"); err != nil || status != "activated" {
		t.Fatal(status, err)
	}
	if err := stateformat.RequireWindowsProfile(s.Dir); err != nil {
		t.Fatal(err)
	}
	assertProfileHistoryUnchanged(t, s.Dir, before)
	if _, err := os.Stat(filepath.Join(s.Dir, stateformat.PlanName)); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("active barrier retained", err)
	}
	stable := treeSnapshot(t, s.Dir)
	if status, err := s.ActivateWindowsProfile(true, "different-informational-version"); err != nil || status != "up_to_date" || !reflect.DeepEqual(stable, treeSnapshot(t, s.Dir)) {
		t.Fatal("repeat changed state", status, err)
	}
}

func TestWindowsProfileActivationRefusesBeforePublication(t *testing.T) {
	for _, kind := range []string{"unconfirmed", "v1", "version", "unknown-journal", "live-writer"} {
		t.Run(kind, func(t *testing.T) {
			s := windowsProfileFixture(t)
			confirm, version := true, "profile-test"
			switch kind {
			case "unconfirmed":
				confirm = false
			case "v1":
				writeMarker(t, s.Dir, StateFormatMarker{Schema: StateFormatSchema, FormatVersion: 1})
			case "version":
				version = ""
			case "unknown-journal":
				p := filepath.Join(s.Dir, stateformat.WindowsProfileDir)
				if err := os.Mkdir(p, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(p, "unknown"), []byte("retain"), 0600); err != nil {
					t.Fatal(err)
				}
			case "live-writer":
				w, err := AcquireWriter(s.Dir)
				if err != nil {
					t.Fatal(err)
				}
				defer w.Release()
			}
			before := treeSnapshot(t, s.Dir)
			if _, err := s.ActivateWindowsProfile(confirm, version); err == nil {
				t.Fatal("unacceptable activation succeeded")
			}
			if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
				t.Fatal("refusal changed state")
			}
		})
	}
}

func TestWindowsProfileEachCheckpointRecovery(t *testing.T) {
	for _, point := range []string{"plan", "archived", "prepared", "marker", "done"} {
		t.Run(point, func(t *testing.T) {
			s := windowsProfileFixture(t)
			before := treeSnapshot(t, s.Dir)
			stop := errors.New("test interruption")
			_, err := s.activateWindowsProfile(true, "profile-test", func(at string) error {
				if at == point {
					return stop
				}
				return nil
			})
			if !errors.Is(err, stop) {
				t.Fatal("fault not reached", err)
			}
			{
				stable := treeSnapshot(t, s.Dir)
				if _, err := Open(s.Dir); err == nil {
					t.Fatal("incomplete state opened")
				}
				if _, err := s.MigrateState("ordinary-retry"); !errors.Is(err, stateformat.ErrWindowsProfileMigration) {
					t.Fatal("ordinary migration bypassed activation barrier", err)
				}
				if !reflect.DeepEqual(stable, treeSnapshot(t, s.Dir)) {
					t.Fatal("blocked open changed state")
				}
			}
			if _, err := s.ActivateWindowsProfile(true, "retry"); err != nil {
				t.Fatal("recovery", err)
			}
			if err := stateformat.RequireWindowsProfile(s.Dir); err != nil {
				t.Fatal(err)
			}
			assertProfileHistoryUnchanged(t, s.Dir, before)
		})
	}
}

func TestWindowsProfileMissingMarkerRecoveryIsBounded(t *testing.T) {
	for _, point := range []string{"plan", "prepared"} {
		t.Run(point, func(t *testing.T) {
			s := windowsProfileFixture(t)
			_, err := s.activateWindowsProfile(true, "test", func(at string) error {
				if at == point {
					return errors.New("stop")
				}
				return nil
			})
			if err == nil {
				t.Fatal("fault")
			}
			if err := os.Remove(filepath.Join(s.Dir, stateformat.MarkerName)); err != nil {
				t.Fatal(err)
			}
			before := treeSnapshot(t, s.Dir)
			_, err = s.ActivateWindowsProfile(true, "retry")
			if point == "prepared" {
				if err != nil {
					t.Fatal(err)
				}
			} else {
				if err == nil || !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
					t.Fatal("unprepared marker loss recovered", err)
				}
			}
		})
	}
}

func TestWindowsProfileCompletedMetadataCannotBeSubstituted(t *testing.T) {
	for _, name := range []string{"plan.json", "prepared.json", "done.json"} {
		t.Run(name, func(t *testing.T) {
			s := windowsProfileFixture(t)
			if _, err := s.ActivateWindowsProfile(true, "test"); err != nil {
				t.Fatal(err)
			}
			p := filepath.Join(s.Dir, stateformat.WindowsProfileDir, name)
			if err := os.WriteFile(p, []byte("{}\n"), 0600); err != nil {
				t.Fatal(err)
			}
			before := treeSnapshot(t, s.Dir)
			if _, err := Open(s.Dir); err == nil {
				t.Fatal("corrupt completion accepted")
			}
			if _, err := s.ActivateWindowsProfile(true, "retry"); err == nil {
				t.Fatal("corrupt completion repaired")
			}
			if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
				t.Fatal("corrupt history mutated")
			}
		})
	}
}

func TestWindowsProfileProcessDeathHelper(t *testing.T) {
	dir := os.Getenv("SIQ_TEST_PROFILE_CRASH_DIR")
	point := os.Getenv("SIQ_TEST_PROFILE_CRASH_POINT")
	if dir == "" || point == "" {
		t.Skip("isolated child only")
	}
	s := &Store{Dir: dir}
	_, err := s.activateWindowsProfile(true, "crash-test", func(at string) error {
		if at == point {
			os.Exit(73)
		}
		return nil
	})
	t.Fatal("fault not reached", err)
}

func TestWindowsProfileRealProcessDeathRecovery(t *testing.T) {
	for _, point := range []string{"plan", "prepared", "marker", "done"} {
		t.Run(point, func(t *testing.T) {
			s := windowsProfileFixture(t)
			before := treeSnapshot(t, s.Dir)
			cmd := exec.Command(os.Args[0], "-test.run=^TestWindowsProfileProcessDeathHelper$")
			cmd.Env = append(os.Environ(), "SIQ_TEST_PROFILE_CRASH_DIR="+s.Dir, "SIQ_TEST_PROFILE_CRASH_POINT="+point)
			output, err := cmd.CombinedOutput()
			var exited *exec.ExitError
			if !errors.As(err, &exited) || exited.ExitCode() != 73 {
				t.Fatalf("child did not reach crash point: %v %s", err, output)
			}
			if _, err := s.ActivateWindowsProfile(true, "retry"); err != nil {
				t.Fatal("death recovery", err)
			}
			if err := stateformat.RequireWindowsProfile(s.Dir); err != nil {
				t.Fatal(err)
			}
			assertProfileHistoryUnchanged(t, s.Dir, before)
		})
	}
}

func TestWindowsProfileOldMigrationMustFinishAndRemainBound(t *testing.T) {
	for _, phase := range []string{"incomplete", "history-drift", "initial-history-drift"} {
		t.Run(phase, func(t *testing.T) {
			s := migrationFixture(t)
			if phase == "incomplete" {
				_, err := s.migrateState("old", func(at string) error {
					if at == "plan" {
						return errors.New("stop")
					}
					return nil
				})
				if err == nil {
					t.Fatal("old migration did not stop")
				}
			} else {
				if _, err := s.MigrateState("old"); err != nil {
					t.Fatal(err)
				}
				if phase == "history-drift" {
					_, err := s.activateWindowsProfile(true, "new", func(at string) error {
						if at == "prepared" {
							return errors.New("stop")
						}
						return nil
					})
					if err == nil {
						t.Fatal("activation did not stop")
					}
				}
				if err := os.WriteFile(filepath.Join(s.Dir, stateformat.MigrationDir, "done.json"), []byte("{}\n"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			before := treeSnapshot(t, s.Dir)
			if _, err := s.ActivateWindowsProfile(true, "retry"); err == nil {
				t.Fatal("unverified old migration accepted")
			}
			if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
				t.Fatal("rejected history modified")
			}
		})
	}
}

func TestWindowsProfileMetadataACLIsRechecked(t *testing.T) {
	for _, name := range []string{"plan.json", "prepared.json", "done.json"} {
		t.Run(name, func(t *testing.T) {
			s := windowsProfileFixture(t)
			if _, err := s.ActivateWindowsProfile(true, "test"); err != nil {
				t.Fatal(err)
			}
			restore := acltest.BroadenRead(t, s.Dir, filepath.Join(s.Dir, stateformat.WindowsProfileDir, name))
			defer restore()
			before := treeSnapshot(t, s.Dir)
			if _, err := Open(s.Dir); err == nil {
				t.Fatal("broad profile metadata accepted")
			}
			if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
				t.Fatal("rejected metadata mutated")
			}
		})
	}
}

func TestWindowsProfileReaderWriterRequirementsRemainIndependent(t *testing.T) {
	s := windowsProfileFixture(t)
	m, err := stateformat.ReadMarker(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	m.MinWriter = stateformat.WriterVersion + 1
	if err := os.WriteFile(filepath.Join(s.Dir, stateformat.MarkerName), migrationJSON(m), 0600); err != nil {
		t.Fatal(err)
	}
	if err := stateformat.Check(s.Dir, false, false); err != nil {
		t.Fatal("read refused a compatible reader", err)
	}
	if err := stateformat.Check(s.Dir, true, false); !errors.Is(err, stateformat.ErrFuture) {
		t.Fatal("future writer accepted", err)
	}
}

func TestWindowsProfileGrantPublicationAndRecoveryRequireCompletedActivation(t *testing.T) {
	s := windowsProfileFixture(t)
	key, err := signing.FromSeed(bytes.Repeat([]byte{13}, 32))
	if err != nil {
		t.Fatal(err)
	}
	adm := admission.Admission{AdmissionID: "adm-profile-gate", ContentHash: strings.Repeat("a", 64), Verdict: "admit_with_conditions", EvidenceIDs: []string{"ev-fixture"}, DeclaredFacts: []admission.DeclaredFact{{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: "read_file"}, Effect: "allow", State: "declared", Authority: "skill_manifest", EvidenceIDs: []string{"ev-fixture"}}}}
	base, err := grant.Build(adm, grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: "inst-profile-gate"}, Platform: "hermes", Now: time.Now().UTC(), Key: key})
	if err != nil {
		t.Fatal(err)
	}
	g, policy, err := grant.PrepareWindowsResources(base.Grant, grant.ResourceEdit{Tools: []string{"read_file"}, Network: []grant.NetworkPatch{}, Models: []string{}, Filesystem: grant.FilesystemPatch{ReadOnly: []string{}, ReadWrite: []string{}}}, true, key)
	if err != nil {
		t.Fatal(err)
	}
	audit := AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: "grant_create", Target: g.GrantID}
	c := GrantCommit{Grant: g, ExpectedRevision: -1, DesiredPolicy: policy, Audit: &audit}
	before := treeSnapshot(t, s.Dir)
	if _, err := s.CommitGrant(c); !errors.Is(err, ErrGrantProfileActivation) {
		t.Fatal("valid new grant bypassed inactive state", err)
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
		t.Fatal("inactive commit wrote policy, audit or journal")
	}
	if _, err := s.ActivateWindowsProfile(true, "test"); err != nil {
		t.Fatal(err)
	}
	seq, err := s.CommitGrant(c)
	if err != nil || seq != 0 {
		t.Fatal("activated publication failed", seq, err)
	}
	got, err := s.GetGrant(g.GrantID)
	if err != nil || got == nil || got.SchemaVersion != "grant/v2" || !grant.Verify(key.Public(), *got) {
		t.Fatal("published signed grant differs", err)
	}
	events, err := s.TailAudit(10)
	if err != nil || len(events) != 1 || events[0].Event != "grant_create" {
		t.Fatal("missing transaction audit", err)
	}
	done := filepath.Join(s.Dir, stateformat.WindowsProfileDir, "done.json")
	if err := os.Rename(done, done+".test-retained"); err != nil {
		t.Fatal(err)
	}
	before = treeSnapshot(t, s.Dir)
	if _, err := s.CommitGrant(c); err == nil {
		t.Fatal("commit retry ignored missing activation proof")
	}
	if _, err := s.GetGrant(g.GrantID); err == nil {
		t.Fatal("grant read ignored missing activation proof")
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
		t.Fatal("failed activation recheck wrote state")
	}
	if err := os.Rename(done+".test-retained", done); err != nil {
		t.Fatal(err)
	}
}
