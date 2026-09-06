package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
)

// pendingReceiptDir is under the Edge state directory. DEV10 / R04: after a
// successful batch upload (or empty successful scan), the receipt is journaled
// here before PostReceipt so a crash cannot leave the control plane stuck in
// status=uploaded with no recovery path on this device.
func pendingReceiptDir() (string, error) {
	dir, err := StateDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "pending_receipts"), nil
}

func pendingReceiptPath(taskID string) (string, error) {
	if taskID == "" || strings.ContainsAny(taskID, `/\:`) || strings.Contains(taskID, "..") {
		return "", fmt.Errorf("pending receipt: invalid task_id %q", taskID)
	}
	dir, err := pendingReceiptDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, taskID+".json"), nil
}

// SavePendingReceipt atomically journals rcpt for later PostReceipt.
func SavePendingReceipt(rcpt *Receipt) error {
	if rcpt == nil || rcpt.TaskID == "" {
		return fmt.Errorf("pending receipt: missing task_id")
	}
	dir, err := pendingReceiptDir()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("pending receipt: mkdir: %w", err)
	}
	path, err := pendingReceiptPath(rcpt.TaskID)
	if err != nil {
		return err
	}
	data, err := json.MarshalIndent(rcpt, "", "  ")
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".receipt-*.tmp")
	if err != nil {
		return err
	}
	cleanup := func() {
		_ = tmp.Close()
		_ = os.Remove(tmp.Name())
	}
	if err := tmp.Chmod(0o600); err != nil {
		cleanup()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		cleanup()
		return err
	}
	if err := tmp.Sync(); err != nil {
		cleanup()
		return err
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmp.Name())
		return err
	}
	if err := os.Rename(tmp.Name(), path); err != nil {
		_ = os.Remove(tmp.Name())
		return err
	}
	return nil
}

// LoadPendingReceipt reads a journaled receipt; missing file → (nil, nil).
func LoadPendingReceipt(taskID string) (*Receipt, error) {
	path, err := pendingReceiptPath(taskID)
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var rcpt Receipt
	if err := json.Unmarshal(data, &rcpt); err != nil {
		return nil, fmt.Errorf("pending receipt: parse %s: %w", path, err)
	}
	if rcpt.TaskID == "" {
		rcpt.TaskID = taskID
	}
	return &rcpt, nil
}

// RemovePendingReceipt deletes the journal entry after a successful PostReceipt.
func RemovePendingReceipt(taskID string) error {
	path, err := pendingReceiptPath(taskID)
	if err != nil {
		return err
	}
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// ListPendingReceiptTaskIDs returns task IDs with journaled receipts.
func ListPendingReceiptTaskIDs() ([]string, error) {
	dir, err := pendingReceiptDir()
	if err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var ids []string
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		ids = append(ids, strings.TrimSuffix(e.Name(), ".json"))
	}
	return ids, nil
}

// receiptPoster is the PostReceipt surface used by DrainPendingReceipts.
type receiptPoster interface {
	PostReceipt(ctx context.Context, taskID string, r *Receipt) error
}

// DrainPendingReceipts posts every journaled receipt then removes the file.
// Failures leave the journal entry for the next run (R04 recovery).
func DrainPendingReceipts(ctx context.Context, cli receiptPoster) (posted int, err error) {
	ids, err := ListPendingReceiptTaskIDs()
	if err != nil {
		return 0, err
	}
	var firstErr error
	for _, id := range ids {
		rcpt, loadErr := LoadPendingReceipt(id)
		if loadErr != nil {
			log.Printf("pending receipt %s: load failed: %v", id, loadErr)
			if firstErr == nil {
				firstErr = loadErr
			}
			continue
		}
		if rcpt == nil {
			continue
		}
		if postErr := cli.PostReceipt(ctx, id, rcpt); postErr != nil {
			log.Printf("pending receipt %s: post failed: %v", id, postErr)
			if firstErr == nil {
				firstErr = postErr
			}
			continue
		}
		if remErr := RemovePendingReceipt(id); remErr != nil {
			log.Printf("pending receipt %s: remove failed after post: %v", id, remErr)
			if firstErr == nil {
				firstErr = remErr
			}
			continue
		}
		posted++
		log.Printf("pending receipt %s: drained (status=%s)", id, rcpt.Status)
	}
	return posted, firstErr
}
