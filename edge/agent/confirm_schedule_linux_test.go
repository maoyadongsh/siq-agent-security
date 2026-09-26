//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/canon"
)

// A device whose control plane is a loopback test server. The local install
// plan origin and the client base must agree for the binding check, so only a
// loopback origin can be substituted; the plan digest is recomputed to match.
func pendingListFixture(t *testing.T, server string) (*State, DiscoverySchedule, time.Time) {
	t.Helper()
	parent := t.TempDir()
	if os.Chmod(parent, 0700) != nil {
		t.Fatal("private fixture")
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", filepath.Join(parent, "private"))
	state, schedule, now := scheduleFixture(t)
	state.ControlPlaneURL = server
	var plan map[string]any
	if json.Unmarshal(state.DiscoveryPlan, &plan) != nil {
		t.Fatal("fixture plan")
	}
	plan["control_plane_origin"] = server
	raw, err := json.Marshal(plan)
	if err != nil {
		t.Fatal(err)
	}
	state.DiscoveryPlan = raw
	if state.DiscoveryPlanSHA256, err = compactPlanDigest(raw); err != nil {
		t.Fatal(err)
	}
	state.Secret = pendingListTestSecret
	if err := state.Save(); err != nil {
		t.Fatal(err)
	}
	// Mirror checkScheduleBinding's canonicalization (json.Number, not float64).
	var value map[string]any
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if decoder.Decode(&value) != nil {
		t.Fatal("fixture plan")
	}
	canonical, err := canon.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256(canonical)
	schedule.PlanDigest = hex.EncodeToString(hash[:])
	return state, schedule, now
}

func pendingListIntent(t *testing.T, base DiscoverySchedule, id string) (DiscoverySchedule, string) {
	t.Helper()
	base.ID = id
	digest, err := base.digest()
	if err != nil {
		t.Fatal(err)
	}
	return base, digest
}

func scheduleStateEntries(t *testing.T) []string {
	t.Helper()
	dir, err := StateDir()
	if err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	return names
}

func TestConfirmScheduleDiscoverRejectsConflictingSources(t *testing.T) {
	root := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", root)
	called := false
	send := func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
		called = true
		return nil, errors.New("synthetic send")
	}
	for _, args := range [][]string{
		{"--discover", "--schedule-id", "eds-" + strings.Repeat("a", 32)},
		{"--discover", "--intent", filepath.Join(root, "intent.json")},
		{"--discover", "--resume"},
		{"--discover", "--schedule-id", "eds-" + strings.Repeat("a", 32), "--resume"},
		{"--discover", "extra"},
		{"--discover", "--interactive", "--confirm-intent-sha256", strings.Repeat("a", 64)},
	} {
		if err := confirmSchedule(context.Background(), args, io.Discard, time.Now(), send); err == nil {
			t.Fatalf("accepted conflicting discovery invocation %v", args)
		}
	}
	if called {
		t.Fatal("conflicting invocation reached the transport")
	}
	if entries, err := os.ReadDir(root); err != nil || len(entries) != 0 {
		t.Fatalf("conflicting invocation touched state: %v %v", entries, err)
	}
}

func TestConfirmScheduleDiscoverHelpStatesReadOnlyBoundary(t *testing.T) {
	var help bytes.Buffer
	if err := confirmSchedule(context.Background(), []string{"--help"}, &help, time.Now(), nil); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"--discover", "Discovery is not authorization", "never grants business permissions", "defaults to cancel"} {
		if !strings.Contains(help.String(), want) {
			t.Fatalf("help missing %q: %s", want, help.String())
		}
	}
}

func TestConfirmScheduleDiscoverZeroOneMany(t *testing.T) {
	// Items must be derived from the same fixture the run loads, because the
	// local binding check compares the plan digest against the stored plan.
	for _, mode := range []string{"zero", "single", "many"} {
		t.Run(mode, func(t *testing.T) {
			server := newPendingListServer(t)
			device, base, at := pendingListFixture(t, server.URL)
			one, oneDigest := pendingListIntent(t, base, pendingScheduleID(1))
			two, twoDigest := pendingListIntent(t, base, pendingScheduleID(2))
			var items []map[string]any
			switch mode {
			case "single":
				items = []map[string]any{pendingListItem(t, one, oneDigest)}
			case "many":
				items = []map[string]any{pendingListItem(t, one, oneDigest), pendingListItem(t, two, twoDigest)}
			}
			server.setPages(jsonPage(t, pendingListWire(t, items, nil, nil)))

			sends := 0
			var output bytes.Buffer
			err := confirmSchedule(context.Background(), []string{"--discover"}, &output, at,
				func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
					sends++
					return nil, errors.New("discovery must never confirm")
				})

			switch mode {
			case "zero":
				if err != nil {
					t.Fatal(err)
				}
				if !strings.Contains(output.String(), "No pending discovery schedule") || !strings.Contains(output.String(), "organization console") {
					t.Fatalf("unhelpful empty result: %s", output.String())
				}
				if strings.Contains(output.String(), "Confirmation acknowledged") {
					t.Fatal("empty result claimed periodic onboarding")
				}
			case "single":
				if err != nil {
					t.Fatal(err)
				}
				for _, want := range []string{oneDigest, one.ID, "Preview only", "Discovery only; no business grants."} {
					if !strings.Contains(output.String(), want) {
						t.Fatalf("preview missing %q: %s", want, output.String())
					}
				}
			case "many":
				if !errors.Is(err, errDiscoverySchedule) {
					t.Fatalf("multi-candidate discovery returned %v", err)
				}
				for _, want := range []string{"Multiple pending discovery schedules", one.ID, two.ID, oneDigest, twoDigest} {
					if !strings.Contains(output.String(), want) {
						t.Fatalf("candidate list missing %q: %s", want, output.String())
					}
				}
			}

			if sends != 0 {
				t.Fatal("discovery phase confirmed a plan")
			}
			for _, request := range server.log() {
				if request.method != http.MethodGet {
					t.Fatalf("discovery phase issued %s", request.method)
				}
			}
			if mode != "single" && len(server.log()) != 1 {
				t.Fatalf("requests=%d", len(server.log()))
			}
			if device.DeviceIdentity == "" {
				t.Fatal("fixture identity missing")
			}
			for _, entry := range scheduleStateEntries(t) {
				if strings.Contains(entry, "discovery-schedule") {
					t.Fatalf("discovery phase wrote %s", entry)
				}
			}
		})
	}
}

func TestConfirmScheduleDiscoverNoCandidateCannotSatisfyConfirmation(t *testing.T) {
	server := newPendingListServer(t)
	server.setPages(jsonPage(t, pendingListWire(t, nil, nil, nil)))
	_, _, at := pendingListFixture(t, server.URL)

	var output bytes.Buffer
	err := confirmSchedule(context.Background(), []string{"--discover", "--confirm-intent-sha256", strings.Repeat("a", 64)}, &output, at,
		func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
			t.Fatal("empty discovery must not reach confirmation transport")
			return nil, nil
		})
	if !errors.Is(err, errDiscoverySchedule) {
		t.Fatalf("explicit confirmation without a candidate returned %v", err)
	}
	if !strings.Contains(output.String(), "No pending discovery schedule") {
		t.Fatalf("empty result was not explained: %s", output.String())
	}

	master, slave := fixturePTY(t)
	defer master.Close()
	old := os.Stdin
	os.Stdin = slave
	defer func() { os.Stdin = old }()
	output.Reset()
	err = confirmSchedule(context.Background(), []string{"--discover", "--interactive"}, &output, at,
		func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
			t.Fatal("empty interactive discovery must not reach confirmation transport")
			return nil, nil
		})
	if !errors.Is(err, errDiscoverySchedule) {
		t.Fatalf("interactive confirmation without a candidate returned %v", err)
	}
	if !strings.Contains(output.String(), "No pending discovery schedule") || strings.Contains(output.String(), "默认取消") {
		t.Fatalf("empty interactive result was not handled before prompting: %s", output.String())
	}
	for _, entry := range scheduleStateEntries(t) {
		if strings.Contains(entry, "discovery-schedule") {
			t.Fatalf("empty confirmation request wrote %s", entry)
		}
	}
}

func TestConfirmScheduleDiscoverIntegrityFailureNamesOnlyScheduleIDs(t *testing.T) {
	broken := pendingScheduleID(3)
	// An integrity entry that is not a plain schedule ID is itself untrusted
	// content and must be refused outright, never echoed.
	const hostile = "CANARY-PENDING-INTENT-4c1d"
	page := pendingListWire(t, nil, []string{broken, hostile}, nil)

	server := newPendingListServer(t)
	server.setPages(jsonPage(t, page))
	_, _, at := pendingListFixture(t, server.URL)
	sends := 0
	var output bytes.Buffer
	err := confirmSchedule(context.Background(), []string{"--discover"}, &output, at,
		func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
			sends++
			return nil, errors.New("integrity failure must not confirm")
		})
	if !errors.Is(err, errDiscoverySchedule) {
		t.Fatalf("hostile integrity entry returned %v", err)
	}
	if sends != 0 {
		t.Fatal("integrity failure confirmed a plan")
	}
	if strings.Contains(output.String(), hostile) {
		t.Fatalf("untrusted integrity entry echoed: %s", output.String())
	}

	// A well-formed but failing schedule ID is reported; its plan is not.
	server2 := newPendingListServer(t)
	server2.setPages(jsonPage(t, pendingListWire(t, nil, []string{broken}, nil)))
	_, _, at2 := pendingListFixture(t, server2.URL)
	var controlled bytes.Buffer
	if err := confirmSchedule(context.Background(), []string{"--discover"}, &controlled, at2,
		func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
			t.Fatal("integrity failure must not confirm")
			return nil, nil
		}); !errors.Is(err, errDiscoverySchedule) {
		t.Fatalf("integrity failure returned %v", err)
	}
	if !strings.Contains(controlled.String(), broken) || !strings.Contains(controlled.String(), "integrity_failed") {
		t.Fatalf("controlled IDs missing: %s", controlled.String())
	}
	// Only the device state and the held task lock may exist: no journal, no
	// receipt, nothing that would imply a confirmation attempt.
	entries := scheduleStateEntries(t)
	if !slices.Contains(entries, "state.json") {
		t.Fatalf("device state missing: %v", entries)
	}
	for _, entry := range entries {
		if strings.Contains(entry, "discovery-schedule") {
			t.Fatalf("integrity failure wrote %s", entry)
		}
	}
}

func TestConfirmScheduleDiscoverInteractiveConfirmsExactlyOnePlan(t *testing.T) {
	server := newPendingListServer(t)
	state, base, _ := pendingListFixture(t, server.URL)
	// Truncate before formatting: the wire timestamp accepts at most six
	// fractional digits, so nanosecond precision must not leak into the intent.
	realNow := time.Now().UTC().Truncate(time.Second)
	schedule := base
	schedule.StartsAt = realNow.Add(-time.Hour).Format(time.RFC3339Nano)
	schedule.ExpiresAt = realNow.Add(time.Hour).Format(time.RFC3339Nano)
	schedule, digest := pendingListIntent(t, schedule, pendingScheduleID(4))
	server.setPages(jsonPage(t, pendingListWire(t, []map[string]any{pendingListItem(t, schedule, digest)}, nil, nil)))

	master, slave := fixturePTY(t)
	old := os.Stdin
	os.Stdin = slave
	defer func() { os.Stdin = old }()

	var requests []DiscoveryScheduleConfirmation
	out := &schedulePromptWriter{}
	out.onPrompt = func() error {
		if !strings.Contains(out.String(), "Intent SHA-256: "+digest) {
			t.Fatal("prompt preceded the discovered intent")
		}
		_, err := master.Write([]byte("yes\n"))
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	err := confirmSchedule(ctx, []string{"--discover", "--interactive"}, out, realNow,
		func(_ context.Context, _ *State, request DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
			requests = append(requests, request)
			return &DiscoveryScheduleState{Schema: "enterprise-discovery-schedule-state/v1",
				ScheduleID: request.ScheduleID, IntentDigest: request.IntentDigest, Status: "active", Revision: 1}, nil
		})
	if err != nil {
		t.Fatal(err)
	}
	if len(requests) != 1 || requests[0].ScheduleID != schedule.ID || requests[0].IntentDigest != digest {
		t.Fatalf("discovery confirmed the wrong request: %+v", requests)
	}
	if requests[0].Identity != state.DeviceIdentity {
		t.Fatal("confirmation identity changed")
	}
	// Discovery is still read-only even when the same run goes on to confirm.
	requestsSeen := server.log()
	if len(requestsSeen) != 1 || requestsSeen[0].method != http.MethodGet {
		t.Fatalf("interactive discovery issued %v", requestsSeen)
	}
	entries := scheduleStateEntries(t)
	for _, want := range []string{"discovery-schedule-pending.json", "discovery-schedule-confirmed.json"} {
		if !slices.Contains(entries, want) {
			t.Fatalf("missing %s in %v", want, entries)
		}
	}
	if strings.Contains(out.String(), state.Secret) || strings.Contains(out.String(), state.SignerSeed) {
		t.Fatal("sensitive state displayed")
	}
}

func TestSetupEnterpriseDiscoverGuidance(t *testing.T) {
	var help bytes.Buffer
	if err := setupEnterprise(context.Background(), []string{"--help"}, &help); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(help.String(), "confirm-discovery-schedule --discover --interactive") {
		t.Fatalf("new-device guidance missing: %s", help.String())
	}
	// enterprise-setup/v1 freezes the service record as the final NDJSON record.
	// The new-device next step belongs in help/runbook text, not a new wire phase
	// that strict consumers have never allowlisted.
	for _, scheduled := range []bool{false, true} {
		var out bytes.Buffer
		actions := setupActions{
			prepare: func() (string, error) { return "/fixture/stage", nil },
			confirm: func() error { return nil },
			install: func(string) error { return nil },
		}
		if scheduled {
			actions.schedule = func() error { return nil }
		}
		if err := runEnterpriseSetup(context.Background(), "registered", false, &out, actions); err != nil {
			t.Fatal(err)
		}
		if strings.Contains(out.String(), "organization_schedule_required_then_discover") ||
			!strings.Contains(out.String(), `"phase":"service"`) {
			t.Fatalf("scheduled=%v changed frozen setup progress: %s", scheduled, out.String())
		}
	}
}

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
