package state

import (
	"bufio"
	"bytes"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func recoveryInput() GrantCommit {
	return GrantCommit{Grant: grant.Grant{GrantID: "recover", Status: "revoked", Platform: "hermes", Subject: grant.Subject{ID: "agent"}}, ExpectedRevision: 0,
		DesiredPolicy: grant.DesiredPolicy{"policy_id": "pol-recover", "version": 1}, Audit: &AuditEvent{At: "2026-09-06T12:00:00Z", Event: "grant_revoke", Target: "recover"}}
}

func TestCommitRejectsInvalidMaterialsBeforePublication(t *testing.T) {
	st, _ := Open(t.TempDir())
	c := recoveryInput()
	c.ExpectedRevision = -1
	c.DesiredPolicy["policy_id"] = "../escape"
	if _, err := st.CommitGrant(c); err == nil {
		t.Fatal("invalid policy accepted")
	}
	entries, _ := os.ReadDir(filepath.Join(st.Dir, "grants"))
	if len(entries) != 0 {
		t.Fatal("grant published before validation")
	}
	c.DesiredPolicy = nil
	c.Audit.Target = "different"
	if _, err := st.CommitGrant(c); err == nil {
		t.Fatal("audit target substitution accepted")
	}
}

func TestRecoveryRequiresWriterAndRefusesCorruption(t *testing.T) {
	st, _ := Open(t.TempDir())
	if _, err := st.RecoverGrantCommits(nil); !errors.Is(err, ErrWriterBusy) {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(st.Dir, "commits", "bad.0.prepare.json"), []byte("null"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := st.ListIncompleteCommits(); err == nil {
		t.Fatal("null journal accepted")
	}
	w, err := AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	if _, err := st.RecoverGrantCommits(w); err == nil {
		t.Fatal("corrupt journal replayed")
	}
}

func TestCommitRecoveryAfterProcessKill(t *testing.T) {
	for _, phase := range []string{"prepared", "policy", "audit", "grant", "done"} {
		t.Run(phase, func(t *testing.T) {
			st, _ := Open(t.TempDir())
			old := recoveryInput().Grant
			old.Status = "deployed"
			if _, err := st.PutGrantCAS(old, -1); err != nil {
				t.Fatal(err)
			}
			original, _ := os.ReadFile(filepath.Join(st.Dir, "grants", "recover.0.json"))
			exe, err := os.Executable()
			if err != nil {
				t.Fatal(err)
			}
			cmd := exec.Command(exe, "-test.run=^TestCommitCrashHelper$")
			cmd.Env = append(os.Environ(), "SIQ_COMMIT_HELPER_DIR="+st.Dir, "SIQ_COMMIT_HELPER_PHASE="+phase)
			stdout, err := cmd.StdoutPipe()
			if err != nil {
				t.Fatal(err)
			}
			if err := cmd.Start(); err != nil {
				t.Fatal(err)
			}
			defer func() { _ = cmd.Process.Kill() }()
			ready := make(chan bool, 1)
			go func() {
				sc := bufio.NewScanner(stdout)
				for sc.Scan() {
					if sc.Text() == "commit-boundary" {
						ready <- true
						return
					}
				}
				ready <- false
			}()
			select {
			case ok := <-ready:
				if !ok {
					t.Fatal("child did not reach boundary")
				}
			case <-time.After(15 * time.Second):
				t.Fatal("child timeout")
			}
			if phase != "done" {
				if got := st.ActiveGrant("hermes", "agent"); got != nil {
					t.Fatal("incomplete revoke left old grant usable")
				}
				if _, _, err := st.GetGrantWithSeq("recover"); !errors.Is(err, ErrIncompleteCommit) {
					t.Fatalf("half-commit visible: %v", err)
				}
			}
			if err := cmd.Process.Kill(); err != nil {
				t.Fatal(err)
			}
			_ = cmd.Wait()
			w, err := AcquireWriter(st.Dir)
			if err != nil {
				t.Fatal(err)
			}
			defer w.Release()
			if _, err := st.RecoverGrantCommits(w); err != nil {
				t.Fatal(err)
			}
			if n, err := st.RecoverGrantCommits(w); err != nil || n != 0 {
				t.Fatalf("replay not idempotent: %d %v", n, err)
			}
			got, seq, err := st.GetGrantWithSeq("recover")
			if err != nil || seq != 1 || got.Status != "revoked" {
				t.Fatalf("recovery: %v %d %v", got, seq, err)
			}
			ev, err := st.TailAudit(10)
			if err != nil || len(ev) != 1 || ev[0].Event != "grant_revoke" {
				t.Fatalf("audit duplicated/lost: %v %v", ev, err)
			}
			after, _ := os.ReadFile(filepath.Join(st.Dir, "grants", "recover.0.json"))
			if !bytes.Equal(original, after) {
				t.Fatal("historical grant changed")
			}
			if _, err := st.CommitGrant(recoveryInput()); err != nil {
				t.Fatal("identical retry failed", err)
			}
			mutated := recoveryInput()
			mutated.Grant.Status = "approved"
			if _, err := st.CommitGrant(mutated); !errors.Is(err, ErrRevisionConflict) {
				t.Fatalf("substitution accepted: %v", err)
			}
		})
	}
}

func TestCommitCrashHelper(t *testing.T) {
	dir := os.Getenv("SIQ_COMMIT_HELPER_DIR")
	if dir == "" {
		return
	}
	st, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	commitBoundary = func(phase string) {
		if phase == os.Getenv("SIQ_COMMIT_HELPER_PHASE") {
			os.Stdout.WriteString("commit-boundary\n")
			select {}
		}
	}
	if _, err := st.CommitGrant(recoveryInput()); err != nil {
		t.Fatal(err)
	}
}
