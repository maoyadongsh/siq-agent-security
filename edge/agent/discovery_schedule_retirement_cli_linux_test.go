//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestRetireScheduleCLIPreviewRejectsDamagedMaterial(t *testing.T) {
	for _, mode := range []string{"broken-journal", "orphan-receipt", "broken-receipt", "linked-journal"} {
		t.Run(mode, func(t *testing.T) {
			e := newRetireCLIEnv(t)
			e.prepareWithReceipt()
			dir, err := StateDir()
			if err != nil {
				t.Fatal(err)
			}
			journal := filepath.Join(dir, scheduleJournalName)
			switch mode {
			case "broken-journal":
				err = os.WriteFile(journal, []byte("{"), 0600)
			case "orphan-receipt":
				err = os.Remove(journal)
			case "broken-receipt":
				err = os.WriteFile(filepath.Join(dir, "discovery-schedule-confirmed.json"), []byte("{}"), 0600)
			case "linked-journal":
				if err = os.Rename(journal, journal+".saved"); err == nil {
					err = os.Symlink(journal+".saved", journal)
				}
			}
			if err != nil {
				t.Fatal(err)
			}
			before := retireStateSnapshot(t)
			out, err := e.run()
			if err == nil || strings.Contains(out, "No local discovery schedule material") {
				t.Fatalf("damaged material reported as absent or valid: err=%v out=%q", err, out)
			}
			if e.calls != 0 || !reflect.DeepEqual(before, retireStateSnapshot(t)) {
				t.Fatal("rejected preview changed files or accessed network")
			}
		})
	}
}

func TestRetireScheduleCLIReusesCompleteArchiveBeforeMarker(t *testing.T) {
	e := newRetireCLIEnv(t)
	e.prepareWithReceipt()
	e.preparePending()
	dir, err := StateDir()
	if err != nil {
		t.Fatal(err)
	}
	archives, err := filepath.Glob(filepath.Join(dir, "discovery-schedule-history-*.json"))
	if err != nil || len(archives) != 1 {
		t.Fatal("expected one archive")
	}
	original, err := os.ReadFile(archives[0])
	if err != nil {
		t.Fatal(err)
	}
	// Synthetic crash boundary: durable history exists, marker not published.
	if err := os.Remove(filepath.Join(dir, scheduleRetirementPendingName)); err != nil {
		t.Fatal(err)
	}
	e.resetCalls()
	if _, err := e.run("--confirm-retire-intent-sha256", e.digest); err != nil {
		t.Fatal(err)
	}
	stored, err := os.ReadFile(archives[0])
	if err != nil || !bytes.Equal(original, stored) || e.calls != 2 {
		t.Fatal("complete archive was not preserved and reused with two online checks")
	}
	if _, err := os.Stat(filepath.Join(dir, "discovery-schedule-retired-"+e.digestOfArchive(stored)+".json")); err != nil {
		t.Fatal("completion record missing")
	}
}

// retireCLIEnv wires one synthetic device state with a counting read-only
// transport. It must not hold the task lock while the CLI under test runs.
type retireCLIEnv struct {
	t       *testing.T
	state   *State
	raw     []byte
	now     time.Time
	journal *discoveryScheduleJournal
	digest  string
	status  string
	client  *Client
	calls   int
}

func newRetireCLIEnv(t *testing.T) *retireCLIEnv {
	t.Helper()
	state, raw, now := scheduleJournalFixture(t)
	e := &retireCLIEnv{t: t, state: state, raw: raw, now: now}
	e.client = newAuthedClient(state)
	e.client.http.Transport = scheduleReadTransport(func(r *http.Request) (*http.Response, error) {
		e.calls++
		if r.Method != "GET" {
			t.Fatal("retirement CLI issued a non-GET request")
		}
		body, _ := json.Marshal(discoveryScheduleSnapshot{Schema: "edge-discovery-schedule-intent/v1",
			Intent: e.raw, Digest: e.digest, Status: e.status, Revision: 2})
		return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(body)), Header: make(http.Header)}, nil
	})
	return e
}

func (e *retireCLIEnv) prepareWithReceipt() {
	e.t.Helper()
	unlock, err := acquireTaskLock()
	if err != nil {
		e.t.Fatal(err)
	}
	defer unlock()
	journal, err := prepareScheduleJournal(e.state, e.raw, 0, true, e.now)
	if err != nil {
		e.t.Fatal(err)
	}
	e.journal = journal
	e.digest = journal.Request.IntentDigest
	if err := saveScheduleConfirmation(journal, &DiscoveryScheduleState{Schema: "enterprise-discovery-schedule-state/v1",
		ScheduleID: journal.Request.ScheduleID, IntentDigest: journal.Request.IntentDigest, Status: "active", Revision: 1}); err != nil {
		e.t.Fatal(err)
	}
}

func (e *retireCLIEnv) preparePending() {
	e.t.Helper()
	e.status = "revoked"
	unlock, err := acquireTaskLock()
	if err != nil {
		e.t.Fatal(err)
	}
	defer unlock()
	if _, err := prepareScheduleRetirement(context.Background(), e.state, e.client, e.digest); err != nil {
		e.t.Fatal(err)
	}
}

func (e *retireCLIEnv) run(args ...string) (string, error) {
	e.t.Helper()
	var out bytes.Buffer
	err := retireSchedule(context.Background(), args, &out, func(*State) *Client { return e.client })
	return out.String(), err
}

func (e *retireCLIEnv) resetCalls() { e.calls = 0 }

func retireStateSnapshot(t *testing.T) map[string]string {
	t.Helper()
	dir, err := StateDir()
	if err != nil {
		t.Fatal(err)
	}
	entries := map[string]string{}
	err = filepath.WalkDir(dir, func(path string, item fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return err
		}
		if item.Type()&fs.ModeSymlink != 0 {
			target, err := os.Readlink(path)
			if err != nil {
				return err
			}
			entries[rel] = "symlink:" + target
			return nil
		}
		if item.IsDir() {
			return nil
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(raw)
		entries[rel] = hex.EncodeToString(sum[:])
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return entries
}

func assertNoRetirementFiles(t *testing.T, dir string) {
	t.Helper()
	for _, pattern := range []string{"discovery-schedule-history-*", "discovery-schedule-retired-*"} {
		matches, err := filepath.Glob(filepath.Join(dir, pattern))
		if err != nil {
			t.Fatal(err)
		}
		if len(matches) != 0 {
			t.Fatalf("unexpected retirement files: %v", matches)
		}
	}
	if _, err := os.Lstat(filepath.Join(dir, scheduleRetirementPendingName)); !os.IsNotExist(err) {
		t.Fatal("unexpected pending marker")
	}
}

func TestRetireScheduleCLIPreviewHelpAndCancel(t *testing.T) {
	t.Run("help", func(t *testing.T) {
		var out bytes.Buffer
		if err := retireSchedule(context.Background(), []string{"--help"}, &out, func(*State) *Client {
			t.Fatal("help constructed a client")
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		for _, want := range []string{"retire-discovery-schedule", "organization management console", "does not stop the user service", "does not revoke agent business permissions", "fails closed"} {
			if !strings.Contains(out.String(), want) {
				t.Fatalf("help missing %q", want)
			}
		}
	})
	t.Run("preview-material", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		before := retireStateSnapshot(t)
		e.resetCalls()
		out, err := e.run()
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(out, e.digest) || !strings.Contains(out, "Preview only") {
			t.Fatalf("preview output incomplete: %s", out)
		}
		if e.calls != 0 {
			t.Fatal("preview issued network traffic")
		}
		after := retireStateSnapshot(t)
		if len(after) != len(before) {
			t.Fatal("preview changed state files")
		}
		for name, sum := range before {
			if after[name] != sum {
				t.Fatalf("preview changed %s", name)
			}
		}
	})
	t.Run("preview-no-material", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		before := retireStateSnapshot(t)
		out, err := e.run()
		if err != nil || !strings.Contains(out, "No local discovery schedule material") {
			t.Fatalf("err=%v out=%s", err, out)
		}
		if e.calls != 0 {
			t.Fatal("preview issued network traffic")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("preview changed %s", name)
			}
		}
	})
	t.Run("preview-pending", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		e.preparePending()
		before := retireStateSnapshot(t)
		e.resetCalls()
		out, err := e.run()
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(out, "Pending retirement transaction") || !strings.Contains(out, e.digest) || !strings.Contains(out, "--resume") {
			t.Fatalf("pending preview incomplete: %s", out)
		}
		if e.calls != 0 {
			t.Fatal("pending preview issued network traffic")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("preview changed %s", name)
			}
		}
	})
	t.Run("interactive-cancel", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		before := retireStateSnapshot(t)
		e.resetCalls()
		if _, err := e.run("--interactive"); err == nil {
			t.Fatal("non-terminal interactive mode approved")
		}
		if e.calls != 0 {
			t.Fatal("interactive cancel issued network traffic")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("interactive cancel changed %s", name)
			}
		}
	})
	t.Run("resume-without-pending", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		out, err := e.run("--resume")
		if err != nil || !strings.Contains(out, "No pending retirement transaction") {
			t.Fatalf("err=%v out=%s", err, out)
		}
		if e.calls != 0 {
			t.Fatal("empty recovery issued network traffic")
		}
	})
}

func TestRetireScheduleCLICompletesWithRevocationRecheck(t *testing.T) {
	e := newRetireCLIEnv(t)
	e.prepareWithReceipt()
	path, err := scheduleJournalPath()
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Dir(path)
	historyBefore, err := os.ReadFile(filepath.Join(dir, scheduleJournalName))
	if err != nil {
		t.Fatal(err)
	}
	e.status = "revoked"
	e.resetCalls()
	out, err := e.run("--confirm-retire-intent-sha256", e.digest)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "Retirement complete") || strings.Contains(out, e.state.Secret) || strings.Contains(out, e.state.SignerSeed) {
		t.Fatalf("completion output unsafe or incomplete: %s", out)
	}
	if e.calls != 2 {
		t.Fatalf("expected prepare and finish revocation reads, got %d", e.calls)
	}
	for _, absent := range []string{path, filepath.Join(dir, "discovery-schedule-confirmed.json"), filepath.Join(dir, scheduleRetirementPendingName)} {
		if _, statErr := os.Lstat(absent); !os.IsNotExist(statErr) {
			t.Fatalf("retired material still present: %s", absent)
		}
	}
	matches, err := filepath.Glob(filepath.Join(dir, "discovery-schedule-history-*.json"))
	if err != nil || len(matches) != 1 {
		t.Fatalf("expected exactly one immutable history copy, got %v (%v)", matches, err)
	}
	stored, err := os.ReadFile(matches[0])
	if err != nil {
		t.Fatal(err)
	}
	var record scheduleRetirementArchive
	if json.Unmarshal(stored, &record) != nil || !bytes.Equal(record.Journal, historyBefore) {
		t.Fatal("history does not preserve original journal bytes")
	}
	if _, err := os.Stat(filepath.Join(dir, "discovery-schedule-retired-"+e.digestOfArchive(stored)+".json")); err != nil {
		t.Fatal("durable completion marker missing")
	}
	if requireNoScheduleRetirement() != nil {
		t.Fatal("completion still blocks normal startup")
	}
}

func TestRetireScheduleCLIResumeRecoversPendingTransaction(t *testing.T) {
	for _, mode := range []string{"both-present", "ack-moved", "both-moved"} {
		t.Run(mode, func(t *testing.T) {
			e := newRetireCLIEnv(t)
			e.prepareWithReceipt()
			e.preparePending()
			path, err := scheduleJournalPath()
			if err != nil {
				t.Fatal(err)
			}
			dir := filepath.Dir(path)
			ack := filepath.Join(dir, "discovery-schedule-confirmed.json")
			historyMatches, err := filepath.Glob(filepath.Join(dir, "discovery-schedule-history-*.json"))
			if err != nil || len(historyMatches) != 1 {
				t.Fatalf("pending archive missing: %v (%v)", historyMatches, err)
			}
			history := historyMatches[0]
			switch mode {
			case "ack-moved":
				if err := os.Rename(ack, ack+".fixture-backup"); err != nil {
					t.Fatal(err)
				}
			case "both-moved":
				if err := os.Rename(ack, ack+".fixture-backup"); err != nil {
					t.Fatal(err)
				}
				if err := os.Rename(path, path+".fixture-backup"); err != nil {
					t.Fatal(err)
				}
			}
			e.resetCalls()
			if _, err := e.run("--resume", "--confirm-retire-intent-sha256", e.digest); err != nil {
				t.Fatal(err)
			}
			if e.calls != 1 {
				t.Fatalf("expected exactly one recovery revocation read, got %d", e.calls)
			}
			for _, absent := range []string{path, ack, filepath.Join(dir, scheduleRetirementPendingName)} {
				if _, statErr := os.Lstat(absent); !os.IsNotExist(statErr) {
					t.Fatalf("recovery left material in place: %s", absent)
				}
			}
			after, err := os.ReadFile(history)
			if err != nil {
				t.Fatal(err)
			}
			other, err := filepath.Glob(filepath.Join(dir, "discovery-schedule-history-*.json"))
			if err != nil || len(other) != 1 || other[0] != history {
				t.Fatalf("recovery created a new archive identity: %v", other)
			}
			if _, err := os.Stat(filepath.Join(dir, "discovery-schedule-retired-"+e.digestOfArchive(after)+".json")); err != nil {
				t.Fatal("durable completion marker missing after recovery")
			}
			if requireNoScheduleRetirement() != nil {
				t.Fatal("recovered retirement still blocks startup")
			}
		})
	}
}

func TestRetireScheduleCLIRejections(t *testing.T) {
	t.Run("lock-conflict", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		unlock, err := acquireTaskLock()
		if err != nil {
			t.Fatal(err)
		}
		defer unlock()
		before := retireStateSnapshot(t)
		e.resetCalls()
		if _, err := e.run("--confirm-retire-intent-sha256", e.digest); err == nil || !strings.Contains(err.Error(), "edge task runner already active") {
			t.Fatalf("lock conflict not reported: %v", err)
		}
		if e.calls != 0 {
			t.Fatal("lock conflict issued network traffic")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("lock conflict changed %s", name)
			}
		}
	})
	t.Run("wrong-digest", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		before := retireStateSnapshot(t)
		e.resetCalls()
		if _, err := e.run("--confirm-retire-intent-sha256", strings.Repeat("f", 64)); err == nil {
			t.Fatal("wrong digest accepted")
		}
		if e.calls != 0 {
			t.Fatal("wrong digest reached the network")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("wrong digest changed %s", name)
			}
		}
	})
	t.Run("active-not-revoked", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		e.status = "active"
		before := retireStateSnapshot(t)
		if _, err := e.run("--confirm-retire-intent-sha256", e.digest); err == nil {
			t.Fatal("active schedule accepted for retirement")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("active rejection changed %s", name)
			}
		}
		assertNoRetirementFiles(t, filepath.Dir(mustJournalPath(t)))
	})
	t.Run("canceled-context", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		before := retireStateSnapshot(t)
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		var out bytes.Buffer
		if err := retireSchedule(ctx, []string{"--confirm-retire-intent-sha256", e.digest}, &out, func(*State) *Client { return e.client }); err == nil {
			t.Fatal("canceled context completed")
		}
		if e.calls != 0 {
			t.Fatal("canceled context issued network traffic")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("canceled context changed %s", name)
			}
		}
	})
	t.Run("expired-timeout", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		before := retireStateSnapshot(t)
		ctx, cancel := context.WithTimeout(context.Background(), -time.Second)
		defer cancel()
		var out bytes.Buffer
		if err := retireSchedule(ctx, []string{"--confirm-retire-intent-sha256", e.digest}, &out, func(*State) *Client { return e.client }); err == nil {
			t.Fatal("expired timeout completed")
		}
		if e.calls != 0 {
			t.Fatal("expired timeout issued network traffic")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("expired timeout changed %s", name)
			}
		}
	})
	t.Run("damaged-marker", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		e.preparePending()
		path, _ := scheduleJournalPath()
		dir := filepath.Dir(path)
		if err := os.WriteFile(filepath.Join(dir, scheduleRetirementPendingName), []byte(`{"schema_version":`), 0600); err != nil {
			t.Fatal(err)
		}
		before := retireStateSnapshot(t)
		e.resetCalls()
		if _, err := e.run("--resume", "--confirm-retire-intent-sha256", e.digest); err == nil {
			t.Fatal("damaged marker accepted")
		}
		if e.calls != 0 {
			t.Fatal("damaged marker reached the network")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("damaged marker handling changed %s", name)
			}
		}
	})
	t.Run("archive-replaced", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		e.preparePending()
		path, _ := scheduleJournalPath()
		history, err := filepath.Glob(filepath.Join(filepath.Dir(path), "discovery-schedule-history-*.json"))
		if err != nil || len(history) != 1 {
			t.Fatalf("archive missing: %v", err)
		}
		raw, err := os.ReadFile(history[0])
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(history[0], append(raw, ' '), 0600); err != nil {
			t.Fatal(err)
		}
		before := retireStateSnapshot(t)
		e.resetCalls()
		if _, err := e.run("--resume", "--confirm-retire-intent-sha256", e.digest); err == nil {
			t.Fatal("replaced archive accepted")
		}
		if e.calls != 0 {
			t.Fatal("replaced archive reached the network")
		}
		for name, sum := range before {
			if retireStateSnapshot(t)[name] != sum {
				t.Fatalf("replaced archive handling changed %s", name)
			}
		}
	})
	t.Run("symlink-original", func(t *testing.T) {
		e := newRetireCLIEnv(t)
		e.prepareWithReceipt()
		path, _ := scheduleJournalPath()
		dir := filepath.Dir(path)
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		copyPath := filepath.Join(t.TempDir(), "journal-copy.json")
		if err := os.WriteFile(copyPath, raw, 0600); err != nil {
			t.Fatal(err)
		}
		if err := os.Remove(path); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(copyPath, path); err != nil {
			t.Fatal(err)
		}
		e.resetCalls()
		if _, err := e.run("--confirm-retire-intent-sha256", e.digest); err == nil {
			t.Fatal("symlinked journal accepted")
		}
		if e.calls != 0 {
			t.Fatal("symlinked journal reached the network")
		}
		assertNoRetirementFiles(t, dir)
	})
}

func TestRetireScheduleCLIRespectsConfirmationBoundaries(t *testing.T) {
	e := newRetireCLIEnv(t)
	e.prepareWithReceipt()
	e.preparePending()
	path, err := scheduleJournalPath()
	if err != nil {
		t.Fatal(err)
	}
	// Pending archives block the existing confirmation and startup paths.
	if _, err := prepareScheduleJournal(e.state, e.raw, 0, true, e.now); err == nil {
		t.Fatal("pending archive permitted new confirmation")
	}
	if loop, err := scheduledHeartbeat(e.state, nil, func(context.Context) error { return nil }); err == nil || loop != nil {
		t.Fatal("pending archive permitted startup")
	}
	if err := confirmSchedule(context.Background(), []string{"--resume"}, io.Discard, e.now,
		func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
			t.Error("confirmation path reached the network during pending retirement")
			return nil, errDiscoverySchedule
		}); err == nil {
		t.Fatal("pending archive permitted the existing confirmation command")
	}
	e.status = "revoked"
	e.resetCalls()
	if _, err := e.run("--resume", "--confirm-retire-intent-sha256", e.digest); err != nil {
		t.Fatal(err)
	}
	// Completion only releases the slots; it never confirms a replacement.
	if requireNoScheduleRetirement() != nil {
		t.Fatal("completion did not release the slots")
	}
	if _, statErr := os.Lstat(path); !os.IsNotExist(statErr) {
		t.Fatal("retirement created or kept a journal")
	}
	if e.calls != 1 {
		t.Fatalf("unexpected network traffic: %d", e.calls)
	}
}

func (e *retireCLIEnv) digestOfArchive(raw []byte) string {
	e.t.Helper()
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func mustJournalPath(t *testing.T) string {
	t.Helper()
	path, err := scheduleJournalPath()
	if err != nil {
		t.Fatal(err)
	}
	return path
}
