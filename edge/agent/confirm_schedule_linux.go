//go:build linux

package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

type scheduleConfirmationReceipt struct {
	Schema        string                 `json:"schema_version"`
	RequestDigest string                 `json:"request_digest"`
	Result        DiscoveryScheduleState `json:"result"`
}

var (
	errScheduleConfirmationUnknown = fmt.Errorf("%w; confirmation_result_unknown; preserve journal and use --resume with the original intent; do not recreate or assume active", errDiscoverySchedule)
	errScheduleReceiptUnstored     = fmt.Errorf("%w; confirmation_receipt_not_saved; preserve journal and existing receipt; do not start service or overwrite recovery files", errDiscoverySchedule)
)

func saveScheduleConfirmation(journal *discoveryScheduleJournal, result *DiscoveryScheduleState) error {
	if result == nil || result.Schema != "enterprise-discovery-schedule-state/v1" || result.Status != "active" ||
		result.ScheduleID != journal.Request.ScheduleID || result.IntentDigest != journal.Request.IntentDigest || result.Revision <= journal.Request.Revision {
		return errDiscoverySchedule
	}
	bytes, err := journal.Request.signedBytes()
	if err != nil {
		return errDiscoverySchedule
	}
	hash := sha256.Sum256(bytes)
	receipt := scheduleConfirmationReceipt{Schema: "edge-discovery-schedule-confirmed/v1", RequestDigest: hex.EncodeToString(hash[:]), Result: *result}
	raw, err := json.Marshal(receipt)
	if err != nil {
		return errDiscoverySchedule
	}
	dir, err := scheduleStateDirectory()
	if err != nil {
		return errDiscoverySchedule
	}
	defer dir.Close()
	const name = "discovery-schedule-confirmed.json"
	fd, err := syscall.Openat(int(dir.Fd()), name, syscall.O_WRONLY|syscall.O_CREAT|syscall.O_EXCL|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err == syscall.EEXIST {
		stateDir, e := StateDir()
		if e != nil {
			return errDiscoverySchedule
		}
		previous, e := readDeviceState(filepath.Join(stateDir, name))
		if e != nil || len(previous) > 8192 {
			return errDiscoverySchedule
		}
		fields, ok := rotationJSONFields(previous, []string{"schema_version", "request_digest", "result"}, true)
		if !ok || !scheduleStateFields(fields["result"]) {
			return errDiscoverySchedule
		}
		var stored scheduleConfirmationReceipt
		if json.Unmarshal(previous, &stored) != nil || stored.Schema != receipt.Schema || stored.RequestDigest != receipt.RequestDigest ||
			stored.Result.Schema != result.Schema || stored.Result.ScheduleID != result.ScheduleID || stored.Result.IntentDigest != result.IntentDigest ||
			stored.Result.Status != "active" || stored.Result.Revision <= journal.Request.Revision {
			return errDiscoverySchedule
		}
		return nil
	}
	if err != nil {
		return errDiscoverySchedule
	}
	file := os.NewFile(uintptr(fd), "schedule-confirmed")
	n, writeErr := file.Write(raw)
	syncErr := file.Sync()
	closeErr := file.Close()
	if writeErr != nil || n != len(raw) || syncErr != nil || closeErr != nil || dir.Sync() != nil {
		return errDiscoverySchedule
	}
	return nil
}

func cmdConfirmSchedule(ctx context.Context, args []string) error {
	return confirmSchedule(ctx, args, os.Stdout, time.Now().UTC(), func(ctx context.Context, state *State, body DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
		return newAuthedClient(state).ConfirmDiscoverySchedule(ctx, body)
	})
}

// Transport injection is test-only, not controlled by flags or environment.
func confirmSchedule(ctx context.Context, args []string, output io.Writer, now time.Time, send func(context.Context, *State, DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error)) error {
	fs := flag.NewFlagSet("confirm-discovery-schedule", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	path := fs.String("intent", "", "")
	scheduleID := fs.String("schedule-id", "", "")
	discover := fs.Bool("discover", false, "")
	resume := fs.Bool("resume", false, "")
	confirmation := fs.String("confirm-intent-sha256", "", "")
	interactive := fs.Bool("interactive", false, "")
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			_, e := io.WriteString(output, "confirm-discovery-schedule (--intent FILE | --schedule-id ID | --discover | --resume) [--interactive | --confirm-intent-sha256 DIGEST]\nWithout confirmation option: preview only; --schedule-id and --discover make authenticated GET requests. Interactive mode requires a terminal and defaults to cancel. Discovery is not authorization: the --discover lookup phase never selects, confirms or writes confirmation material; with more than one pending plan it lists candidates and stops, so choose explicitly with --schedule-id. Only an exact --confirm-intent-sha256 or a terminal yes confirms, and confirmation never grants business permissions.\n")
			return e
		}
		return errDiscoverySchedule
	}
	sources := 0
	for _, selected := range []bool{*resume, *path != "", *scheduleID != "", *discover} {
		if selected {
			sources++
		}
	}
	if fs.NArg() != 0 || sources != 1 || ctx.Err() != nil {
		return errDiscoverySchedule
	}
	if *interactive {
		if *confirmation != "" {
			return errDiscoverySchedule
		}
		if _, err := terminalState(os.Stdin); err != nil {
			return errInteractive
		}
	}
	unlock, err := acquireTaskLock()
	if err != nil {
		return errDiscoverySchedule
	}
	defer unlock()
	if requireNoScheduleRetirement() != nil {
		return errDiscoverySchedule
	}
	state, err := loadRotationState()
	if err != nil {
		return errDiscoverySchedule
	}
	var journal *discoveryScheduleJournal
	var raw []byte
	if *resume {
		journal, err = readScheduleJournal(state)
		if err != nil {
			return errDiscoverySchedule
		}
		raw = journal.Intent
	} else if *discover {
		found, err := newAuthedClient(state).discoverPendingSchedules(ctx)
		if err != nil {
			return reportPendingScheduleDiscovery(output, found, err)
		}
		switch len(found.Candidates) {
		case 0:
			// Honest empty result: no confirmation request exists, and periodic
			// discovery is not enabled by this command. A pure lookup succeeded,
			// but a caller that explicitly requested confirmation must not receive
			// a success exit when no confirmation occurred.
			if _, err = io.WriteString(output, "No pending discovery schedule for this device. Nothing is waiting for local confirmation, so no request was created and no periodic discovery is enabled; ask the organization console to create a plan for this device, then retry with --discover.\n"); err != nil {
				return errDiscoverySchedule
			}
			if *interactive || *confirmation != "" {
				return errDiscoverySchedule
			}
			return nil
		case 1:
			raw = found.Candidates[0].Intent
		default:
			return listPendingScheduleCandidates(output, found.Candidates)
		}
	} else if *scheduleID != "" {
		raw, err = newAuthedClient(state).fetchDiscoverySchedule(ctx, *scheduleID)
		if err != nil {
			return errDiscoverySchedule
		}
	} else {
		raw, err = readInstallDocument(*path)
		if err != nil {
			return errDiscoverySchedule
		}
	}
	schedule, err := parseDiscoverySchedule(raw)
	if err != nil {
		return errDiscoverySchedule
	}
	if !*resume {
		if err = checkScheduleBinding(state, *schedule, now); err != nil {
			return errDiscoverySchedule
		}
	}
	plan, err := installplan.Parse(state.DiscoveryPlan)
	if err != nil {
		return errDiscoverySchedule
	}
	digest, err := schedule.digest()
	if err != nil {
		return errDiscoverySchedule
	}
	if _, err = fmt.Fprintf(output, "Discovery only; no business grants.\nDevice: %q\nTenant: %q\nEnvironment: %q\nOrigin: %q\nSchedule: %s\nInterval: %d seconds; maximum rounds: %d\nWindow: %s -> %s\nIntent SHA-256: %s\n",
		state.DeviceIdentity, plan.TenantID, state.EnvironmentID, state.ControlPlaneURL, schedule.ID, schedule.Interval, schedule.MaxRuns, schedule.StartsAt, schedule.ExpiresAt, digest); err != nil {
		return errDiscoverySchedule
	}
	for _, connector := range plan.Connectors {
		if _, err = fmt.Fprintf(output, "Connector %q roots=%q include=%q\n", connector.ID, connector.Scope.Roots, connector.Scope.Include); err != nil {
			return errDiscoverySchedule
		}
	}
	if *interactive {
		if err := confirmDisplayedSchedule(ctx, os.Stdin, output); err != nil {
			return err
		}
		*confirmation = digest
		// The user may wait at the prompt: re-evaluate expiry and timestamp after
		// consent. Resume still sends the original durable request, never resigns.
		now = time.Now().UTC()
	}
	if *confirmation == "" {
		_, err = io.WriteString(output, "Preview only: no journal or confirmation request created. Review the scope and repeat with the exact --confirm-intent-sha256.\n")
		return err
	}
	if *confirmation != digest || ctx.Err() != nil {
		return errDiscoverySchedule
	}
	end, _ := time.Parse(time.RFC3339Nano, schedule.ExpiresAt)
	if !now.Before(end) {
		return errDiscoverySchedule
	}
	if !*resume {
		journal, err = prepareScheduleJournal(state, raw, 0, true, now)
		if err != nil {
			return errDiscoverySchedule
		}
	}
	result, err := send(ctx, state, journal.Request)
	if err != nil {
		return errScheduleConfirmationUnknown
	}
	if saveScheduleConfirmation(journal, result) != nil {
		return errScheduleReceiptUnstored
	}
	_, err = io.WriteString(output, "Confirmation acknowledged; history retained. No scan dispatched by this command; no runtime protection claim.\n")
	return err
}

// A discovery failure leaves only the controlled reason. An integrity failure
// may additionally name the affected schedule IDs — never their intents,
// upstream bodies, URLs or credentials.
func reportPendingScheduleDiscovery(output io.Writer, found *pendingScheduleDiscovery, err error) error {
	if errors.Is(err, errPendingScheduleIntegrity) && found != nil {
		if _, writeErr := io.WriteString(output, "Pending discovery schedules failed integrity verification; nothing selected, confirmed or written. Report these schedule IDs to the organization console:\n"); writeErr != nil {
			return errDiscoverySchedule
		}
		for _, id := range found.IntegrityFailed {
			if _, writeErr := fmt.Fprintf(output, "Schedule %s integrity_failed\n", id); writeErr != nil {
				return errDiscoverySchedule
			}
		}
	}
	return err
}

// Discovery never chooses for the operator: more than one pending plan is listed
// and abandoned so the next step must be an explicit --schedule-id.
func listPendingScheduleCandidates(output io.Writer, candidates []pendingScheduleCandidate) error {
	if _, err := io.WriteString(output, "Multiple pending discovery schedules; nothing selected, confirmed or written. Re-run with the exact --schedule-id:\n"); err != nil {
		return errDiscoverySchedule
	}
	for _, candidate := range candidates {
		if _, err := fmt.Fprintf(output, "Schedule %s status=%s revision=%d window=%s -> %s intent_sha256=%s\n",
			candidate.ID, candidate.Status, candidate.Revision, candidate.StartsAt, candidate.ExpiresAt, candidate.Digest); err != nil {
			return errDiscoverySchedule
		}
	}
	return errDiscoverySchedule
}

// Scope, budget and expiry must have been successfully displayed by the caller.
func confirmDisplayedSchedule(ctx context.Context, input io.Reader, output io.Writer) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if _, err := io.WriteString(output, "仅确认上方周期和范围的资产采集，不授予业务权限。输入 yes 确认，其他输入取消 [默认取消]："); err != nil {
		return errInteractive
	}
	type answer struct {
		value string
		err   error
	}
	done := make(chan answer, 1)
	go func() { value, err := readConfirmation(input); done <- answer{value, err} }()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case a := <-done:
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if a.err != nil || strings.TrimSuffix(a.value, "\r") != "yes" {
			return errInteractive
		}
		return nil
	}
}
