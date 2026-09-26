//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestScheduleInteractiveConsentDefaultsToCancel(t *testing.T) {
	for _, input := range []string{"yes\n", "yes\r\n", "\n", "no\n", "YES\n", " yes\n", "yes", "", strings.Repeat("x", 1024) + "\n"} {
		t.Run(fmtConsentName(input), func(t *testing.T) {
			var output bytes.Buffer
			err := confirmDisplayedSchedule(context.Background(), strings.NewReader(input), &output)
			accepted := input == "yes\n" || input == "yes\r\n"
			if (err == nil) != accepted {
				t.Fatalf("accepted=%v err=%v", accepted, err)
			}
			if !strings.Contains(output.String(), "默认取消") || !strings.Contains(output.String(), "不授予业务权限") {
				t.Fatal("missing consent boundary")
			}
		})
	}
}

func fmtConsentName(input string) string {
	if len(input) > 32 {
		return "oversized"
	}
	return "input=" + input
}

type schedulePromptWriter struct {
	bytes.Buffer
	onPrompt func() error
}

func (w *schedulePromptWriter) Write(p []byte) (int, error) {
	if strings.Contains(string(p), "默认取消") {
		if err := w.onPrompt(); err != nil {
			return 0, err
		}
	}
	return w.Buffer.Write(p)
}

func (w *schedulePromptWriter) WriteString(s string) (int, error) { return w.Write([]byte(s)) }

func TestConfirmScheduleTerminalConsentJournalBoundary(t *testing.T) {
	for _, mode := range []string{"yes", "cancel", "output_failure", "elapsed_expiry"} {
		t.Run(mode, func(t *testing.T) {
			state, raw, _ := scheduleJournalFixture(t)
			schedule, err := parseDiscoverySchedule(raw)
			if err != nil {
				t.Fatal(err)
			}
			now := time.Now().UTC().Truncate(time.Second)
			schedule.StartsAt = now.Add(-time.Hour).Format(time.RFC3339Nano)
			schedule.ExpiresAt = now.Add(time.Hour).Format(time.RFC3339Nano)
			if mode == "elapsed_expiry" {
				// Initial read precedes expiry; post-prompt wall clock is past it.
				// No sleep or production clock override is needed.
				schedule.ExpiresAt = now.Add(-time.Minute).Format(time.RFC3339Nano)
				now = now.Add(-2 * time.Minute)
			}
			raw, err = json.Marshal(schedule)
			if err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(t.TempDir(), "intent.json")
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			master, slave := fixturePTY(t)
			old := os.Stdin
			os.Stdin = slave
			defer func() { os.Stdin = old }()
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			prompted, sent := false, false
			out := &schedulePromptWriter{}
			out.onPrompt = func() error {
				prompted = true
				if !strings.Contains(out.String(), "Intent SHA-256:") || !strings.Contains(out.String(), "Connector") {
					t.Fatal("prompt preceded complete scope")
				}
				if mode == "output_failure" {
					return errors.New("synthetic writer failure")
				}
				if mode == "cancel" {
					cancel()
				}
				_, err := master.Write([]byte("yes\n"))
				return err
			}
			err = confirmSchedule(ctx, []string{"--intent", path, "--interactive"}, out, now,
				func(_ context.Context, s *State, request DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
					sent = true
					journal, err := readScheduleJournal(s)
					if err != nil || journal.Request != request {
						t.Fatal("send before exact durable journal")
					}
					return &DiscoveryScheduleState{Schema: "enterprise-discovery-schedule-state/v1", ScheduleID: request.ScheduleID, IntentDigest: request.IntentDigest, Status: "active", Revision: 1}, nil
				})
			accepted := mode == "yes"
			if !prompted || sent != accepted || (err == nil) != accepted {
				t.Fatalf("mode=%s prompt=%v sent=%v err=%v", mode, prompted, sent, err)
			}
			journalPath, _ := scheduleJournalPath()
			for _, file := range []string{journalPath, filepath.Join(filepath.Dir(journalPath), "discovery-schedule-confirmed.json")} {
				_, err := os.Stat(file)
				if accepted && err != nil || !accepted && !os.IsNotExist(err) {
					t.Fatal("incorrect persisted consent", err)
				}
			}
			if strings.Contains(out.String(), state.Secret) || strings.Contains(out.String(), state.SignerSeed) {
				t.Fatal("sensitive state displayed")
			}
		})
	}
}

func TestScheduleInteractiveOutputFailureAndCancellation(t *testing.T) {
	if err := confirmDisplayedSchedule(context.Background(), strings.NewReader("yes\n"), failedSetupOutput{}); err == nil {
		t.Fatal("accepted failed display")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	var output bytes.Buffer
	if err := confirmDisplayedSchedule(ctx, strings.NewReader("yes\n"), &output); !errors.Is(err, context.Canceled) || output.Len() != 0 {
		t.Fatal("pre-cancel was ignored")
	}
	ctx, cancel = context.WithCancel(context.Background())
	defer cancel()
	reader, writer := io.Pipe()
	defer reader.Close()
	defer writer.Close()
	result := make(chan error, 1)
	go func() { result <- confirmDisplayedSchedule(ctx, reader, io.Discard) }()
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("cancelled prompt hung")
	}
}

func TestScheduleInteractiveRejectsPipeBeforeStateOrSend(t *testing.T) {
	root := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", root)
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	defer writer.Close()
	original := os.Stdin
	os.Stdin = reader
	defer func() { os.Stdin = original }()
	send := func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
		t.Fatal("unexpected confirmation send")
		return nil, nil
	}
	for _, args := range [][]string{{"--intent", "missing", "--interactive"}, {"--resume", "--interactive", "--confirm-intent-sha256", strings.Repeat("a", 64)}} {
		if err := confirmSchedule(context.Background(), args, io.Discard, time.Now(), send); err == nil {
			t.Fatal("accepted invalid interactive invocation")
		}
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 0 {
		t.Fatal("invalid invocation touched state", err)
	}
}

func TestConfirmSchedulePreviewExplicitSendAndExactResume(t *testing.T) {
	state, raw, now := scheduleJournalFixture(t)
	intentPath := filepath.Join(t.TempDir(), "intent.json")
	if err := os.WriteFile(intentPath, raw, 0600); err != nil {
		t.Fatal(err)
	}
	schedule, _ := parseDiscoverySchedule(raw)
	digest, _ := schedule.digest()
	var output bytes.Buffer
	var requests []DiscoveryScheduleConfirmation
	failed := true
	send := func(ctx context.Context, s *State, r DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
		journal, err := readScheduleJournal(s)
		if err != nil || journal.Request != r {
			t.Fatal("sent before durable journal")
		}
		requests = append(requests, r)
		if failed {
			return nil, errors.New("synthetic network failure")
		}
		return &DiscoveryScheduleState{Schema: "enterprise-discovery-schedule-state/v1", ScheduleID: r.ScheduleID,
			IntentDigest: r.IntentDigest, Status: "active", Revision: 1}, nil
	}
	args := []string{"--intent", intentPath}
	if err := confirmSchedule(context.Background(), args, &output, now, send); err != nil {
		t.Fatal(err)
	}
	path, _ := scheduleJournalPath()
	if _, err := os.Lstat(path); !os.IsNotExist(err) || len(requests) != 0 {
		t.Fatal("preview wrote or sent")
	}
	if !strings.Contains(output.String(), digest) || !strings.Contains(output.String(), "900") || !strings.Contains(output.String(), "config.yaml") || strings.Contains(output.String(), state.Secret) {
		t.Fatal("unsafe/incomplete preview")
	}
	bad := append(append([]string(nil), args...), "--confirm-intent-sha256", strings.Repeat("f", 64))
	if err := confirmSchedule(context.Background(), bad, &output, now, send); err == nil || len(requests) != 0 {
		t.Fatal("mismatched confirmation sent")
	}
	args = append(args, "--confirm-intent-sha256", digest)
	if err := confirmSchedule(context.Background(), args, &output, now, send); err != errScheduleConfirmationUnknown || !errors.Is(err, errDiscoverySchedule) || len(requests) != 1 {
		t.Fatal("network failure hidden")
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := confirmSchedule(context.Background(), args, &output, now.Add(time.Minute), send); err == nil || len(requests) != 1 {
		t.Fatal("pending journal replaced")
	}
	failed = false
	resume := []string{"--resume", "--confirm-intent-sha256", digest}
	if err := confirmSchedule(context.Background(), resume, &output, now.Add(time.Minute), send); err != nil {
		t.Fatal(err)
	}
	if len(requests) != 2 || requests[0] != requests[1] {
		t.Fatal("resume changed request")
	}
	after, _ := os.ReadFile(path)
	if !bytes.Equal(before, after) {
		t.Fatal("journal changed")
	}
	ackPath := filepath.Join(filepath.Dir(path), "discovery-schedule-confirmed.json")
	ack, err := os.ReadFile(ackPath)
	if err != nil {
		t.Fatal(err)
	}
	var receipt scheduleConfirmationReceipt
	if json.Unmarshal(ack, &receipt) != nil || receipt.Result.Status != "active" {
		t.Fatal("ack not persisted")
	}
	if err := confirmSchedule(context.Background(), resume, &output, now.Add(2*time.Minute), send); err != nil {
		t.Fatal(err)
	}
	current, _ := os.ReadFile(ackPath)
	if !bytes.Equal(ack, current) {
		t.Fatal("ack overwritten")
	}
}

func TestConfirmScheduleLockExpiryAndUnknownReceipt(t *testing.T) {
	state, raw, now := scheduleJournalFixture(t)
	journal, err := prepareScheduleJournal(state, raw, 0, true, now)
	if err != nil {
		t.Fatal(err)
	}
	digest := journal.Request.IntentDigest
	args := []string{"--resume", "--confirm-intent-sha256", digest}
	calls := 0
	send := func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
		calls++
		return &DiscoveryScheduleState{
			Schema: "enterprise-discovery-schedule-state/v1", ScheduleID: journal.Request.ScheduleID,
			IntentDigest: digest, Status: "active", Revision: 1}, nil
	}
	var output bytes.Buffer
	unlock, err := acquireTaskLock()
	if err != nil {
		t.Fatal(err)
	}
	err = confirmSchedule(context.Background(), args, &output, now, send)
	unlock()
	if err == nil || calls != 0 {
		t.Fatal("active service lock bypassed")
	}
	if err := confirmSchedule(context.Background(), args, &output, now.Add(24*time.Hour), send); err == nil || calls != 0 {
		t.Fatal("expired intent sent")
	}
	path, _ := scheduleJournalPath()
	ack := filepath.Join(filepath.Dir(path), "discovery-schedule-confirmed.json")
	if err := os.WriteFile(ack, []byte("partial-existing-record"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := confirmSchedule(context.Background(), args, &output, now, send); err != errScheduleReceiptUnstored || !errors.Is(err, errDiscoverySchedule) {
		t.Fatal("partial ack overwritten")
	}
	rawAck, _ := os.ReadFile(ack)
	if string(rawAck) != "partial-existing-record" {
		t.Fatal("unknown object overwritten")
	}
}
