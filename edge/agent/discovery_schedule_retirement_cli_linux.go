//go:build linux

package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

const retireScheduleHelp = `retire-discovery-schedule [--resume] [--interactive | --confirm-retire-intent-sha256 DIGEST]
Archive a retired discovery schedule after its online revocation has been re-verified.
Without a confirmation option: local read-only preview only; no network request and no file change.
--resume consumes an existing pending retirement transaction only; it never resigns, replaces or confirms a plan.
Prerequisites and limits:
- First revoke the old schedule in the organization management console; this command never calls the revoke API.
- This command does not stop the user service; on task-lock conflict resolve the active runner by the existing process.
- Archiving does not revoke agent business permissions and does not cancel dispatched tasks.
- A new schedule always requires its own independent confirmation; the archived confirmation is never inherited.
- Archived history is retained and traceable; only the fixed confirmation slots are released.
- Any unverifiable condition (network, unknown status, identity or digest mismatch, damaged records) fails closed; nothing is bypassed.
`

var errScheduleRetirementIncomplete = fmt.Errorf("%w; retirement_pending; the archive and recovery marker are preserved; resolve the cause and use retire-discovery-schedule --resume", errDiscoverySchedule)

func cmdRetireSchedule(ctx context.Context, args []string) error {
	return retireSchedule(ctx, args, os.Stdout, func(state *State) *Client { return newAuthedClient(state) })
}

// Transport injection is test-only, not controlled by flags or environment.
func retireSchedule(ctx context.Context, args []string, output io.Writer, newClient func(*State) *Client) error {
	fs := flag.NewFlagSet("retire-discovery-schedule", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	confirmation := fs.String("confirm-retire-intent-sha256", "", "")
	interactive := fs.Bool("interactive", false, "")
	resume := fs.Bool("resume", false, "")
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			_, e := io.WriteString(output, retireScheduleHelp)
			return e
		}
		return errDiscoverySchedule
	}
	if fs.NArg() != 0 || ctx.Err() != nil || (*interactive && *confirmation != "") {
		return errDiscoverySchedule
	}
	state, err := loadRotationState()
	if err != nil {
		return errDiscoverySchedule
	}
	dir, err := scheduleStateDirectory()
	if err != nil {
		return errDiscoverySchedule
	}
	defer dir.Close()
	pending, journal, archiveDigest, pendingErr := readRetirementPreview(dir, state)
	if pendingErr != nil {
		return pendingErr
	}
	if *resume && pending == nil {
		// Consuming a transaction that does not exist would fake a recovery.
		_, err = io.WriteString(output, "No pending retirement transaction; nothing to recover.\n")
		return err
	}
	if *interactive {
		if _, err = terminalState(os.Stdin); err != nil {
			return errInteractive
		}
	}
	if pending != nil {
		if _, err = writeRetirementPreview(output, state, journal, true, archiveDigest); err != nil {
			return errDiscoverySchedule
		}
	} else {
		local, localErr := readLocalRetirementPreview(dir, state)
		if localErr != nil {
			return errDiscoverySchedule
		}
		if local == nil {
			if _, err = io.WriteString(output, "No local discovery schedule material to retire.\n"); err != nil {
				return errDiscoverySchedule
			}
			if *confirmation == "" && !*interactive {
				return nil
			}
			return errDiscoverySchedule
		}
		journal = local
		if _, err = writeRetirementPreview(output, state, journal, false, ""); err != nil {
			return errDiscoverySchedule
		}
	}
	digest := *confirmation
	if *interactive {
		if err := confirmDisplayedRetirement(ctx, os.Stdin, output); err != nil {
			return err
		}
		digest = journal.Request.IntentDigest
	}
	if digest == "" {
		_, err = io.WriteString(output, "Preview only: nothing changed. Revoke the old schedule in the organization console, then repeat with the exact --confirm-retire-intent-sha256 or --interactive.\n")
		return err
	}
	if digest != journal.Request.IntentDigest || ctx.Err() != nil {
		return errDiscoverySchedule
	}
	if pending != nil && !*resume {
		return fmt.Errorf("%w; pending_retirement_exists; use --resume to finish or resume the archived transaction", errDiscoverySchedule)
	}
	unlock, err := acquireTaskLock()
	if err != nil {
		return err
	}
	defer unlock()
	client := newClient(state)
	if pending != nil {
		if err := finishScheduleRetirement(ctx, state, client, digest); err != nil {
			return err
		}
	} else {
		if _, err := prepareScheduleRetirement(ctx, state, client, digest); err != nil {
			return err
		}
		if err := finishScheduleRetirement(ctx, state, client, digest); err != nil {
			return errScheduleRetirementIncomplete
		}
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	_, err = io.WriteString(output, "Retirement complete: online revocation re-verified, originals released, history retained. This did not revoke business permissions, stop the service or confirm a new schedule; confirm any replacement independently.\n")
	return err
}

// Only absence of both fixed slots means no material. Invalid or orphaned
// records must not be hidden by the journal reader's intentionally fixed error.
func readLocalRetirementPreview(dir *os.File, state *State) (*discoveryScheduleJournal, error) {
	raw, journalErr := readScheduleRetirementFile(dir, scheduleJournalName)
	ack, receiptErr := readScheduleRetirementFile(dir, "discovery-schedule-confirmed.json")
	if errors.Is(journalErr, os.ErrNotExist) && errors.Is(receiptErr, os.ErrNotExist) {
		return nil, nil
	}
	if journalErr != nil || (receiptErr != nil && !errors.Is(receiptErr, os.ErrNotExist)) {
		return nil, errDiscoverySchedule
	}
	journal, err := parseScheduleJournal(state, raw)
	if err != nil || (receiptErr == nil && !validScheduleAcknowledgement(ack, journal)) {
		return nil, errDiscoverySchedule
	}
	return journal, nil
}

// readRetirementPreview returns the pending transaction when one exists, without
// network access. A damaged pending record fails closed even for preview.
func readRetirementPreview(dir *os.File, state *State) (*scheduleRetirementArchive, *discoveryScheduleJournal, string, error) {
	path, err := StateDir()
	if err != nil {
		return nil, nil, "", errDiscoverySchedule
	}
	if _, err := os.Lstat(filepath.Join(path, scheduleRetirementPendingName)); errors.Is(err, os.ErrNotExist) {
		return nil, nil, "", nil
	} else if err != nil {
		return nil, nil, "", errDiscoverySchedule
	}
	record, journal, markerRaw, err := readPendingScheduleRetirement(dir, state)
	if err != nil {
		return nil, nil, "", errDiscoverySchedule
	}
	var marker scheduleRetirementPending
	if json.Unmarshal(markerRaw, &marker) != nil {
		return nil, nil, "", errDiscoverySchedule
	}
	return record, journal, marker.Archive, nil
}

func writeRetirementPreview(output io.Writer, state *State, journal *discoveryScheduleJournal, archived bool, archiveDigest string) (int, error) {
	schedule, err := parseDiscoverySchedule(journal.Intent)
	if err != nil {
		return 0, errDiscoverySchedule
	}
	header := "Old discovery schedule (not yet archived)\n"
	if archived {
		header = "Pending retirement transaction (originals may already be archived)\n"
	}
	text := fmt.Sprintf("%sDiscovery only; archiving grants no business permissions and stops no service.\nDevice: %q\nOrigin: %q\nSchedule: %s\nInterval: %d seconds; maximum rounds: %d\nWindow: %s -> %s\nIntent SHA-256: %s\n",
		header, state.DeviceIdentity, state.ControlPlaneURL, schedule.ID, schedule.Interval, schedule.MaxRuns, schedule.StartsAt, schedule.ExpiresAt, journal.Request.IntentDigest)
	if archived {
		text += fmt.Sprintf("Archive: discovery-schedule-history-%s.json\nRecovery: repeat with --resume and the same digest.\n", archiveDigest)
	}
	return fmt.Fprint(output, text)
}

// Scope and revocation consequences must have been displayed by the caller.
func confirmDisplayedRetirement(ctx context.Context, input io.Reader, output io.Writer) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if _, err := io.WriteString(output, "确认归档上方旧周期？需先在组织管理端撤销；本命令不停止服务、不撤销业务权限、不取消已派发任务、不确认新计划。输入 yes 确认，其他输入取消 [默认取消]："); err != nil {
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
