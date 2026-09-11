package runtimecheck

import (
	"context"
	"errors"
	"os"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/state"
)

func (m *Manager) execute(ctx context.Context, r *run, target adapterinstall.RuntimeTarget, nonce string) {
	defer close(r.done)
	defer r.cancel()
	m.mu.Lock()
	p, err := m.prepare(r)
	if err == nil {
		r.record.Result.Status, r.record.Result.Reason = "waiting_host", "runtime_check_waiting_host"
		err = m.persist(&r.record)
	}
	m.mu.Unlock()
	if err == nil {
		err = m.launchHost(ctx, r, target, nonce, p)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	reason := "runtime_check_passed"
	status := "passed"
	if err != nil {
		status, reason = "failed", err.Error()
	}
	if ctx.Err() != nil {
		status, reason = "cancelled", "runtime_check_cancelled"
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			status, reason = "failed", "runtime_check_timeout"
		}
	}
	if status == "passed" {
		if err := m.verify(r, p); err != nil {
			status, reason = "failed", err.Error()
		}
		current, err := m.snapshot(r.record.Result.InstanceID)
		if err != nil || current.Digest != r.record.Result.Snapshot {
			status, reason = "invalidated", "runtime_check_snapshot_changed"
		}
	}
	m.cleanup(&r.record)
	if r.record.Result.Cleanup != "complete" {
		status, reason = "failed", "runtime_check_cleanup_failed"
	}
	now := time.Now().UTC().Format(time.RFC3339Nano)
	r.record.Result.Status, r.record.Result.Reason, r.record.Result.FinishedAt = status, reason, &now
	if err := m.o.Store.AppendAudit(state.AuditEvent{At: now, Event: "runtime_check_finish", ActorID: r.record.Actor, Target: r.record.Result.ID}); err != nil {
		r.record.Result.Status, r.record.Result.Reason = "failed", "runtime_check_audit_failed"
	}
	if err := m.persist(&r.record); err != nil {
		// Keep the failed run visible in memory and block further launches; the
		// signed unfinished journal is recovered on the next service start.
		r.record.Result.Status, r.record.Result.Reason = "failed", "runtime_check_record_failed"
		r.credential = [32]byte{}
		return
	}
	r.credential = [32]byte{}
	if m.active == r {
		m.active = nil
	}
}

func (m *Manager) verify(r *run, p probes) error {
	if r.session == "" {
		return errors.New("runtime_check_native_session_missing")
	}
	if _, err := os.Lstat(p.forbidden); !errors.Is(err, os.ErrNotExist) {
		return errors.New("runtime_check_forbidden_effect")
	}
	read, err := m.o.Chain.ReadLimited(receipt.ReadLimit{MaxRecords: 100000, MaxBytes: 64 << 20})
	if err != nil || read.Truncated || receipt.Verify(read.Receipts, m.o.Key.Public()) != nil {
		return errors.New("runtime_check_receipts_unavailable")
	}
	expected := map[string]string{"rc-first": "allow", "rc-denied": "deny", "rc-last": "allow"}
	counts := map[string]int{}
	decisions := map[string]receipt.Receipt{}
	for _, item := range read.Receipts {
		if item.SessionID != r.session || item.AgentID == nil || *item.AgentID != agentID(r.record.Result.ID) {
			continue
		}
		if item.IntentID != r.record.IntentID || item.IntentDigest != r.record.IntentDigest {
			return errors.New("runtime_check_receipt_binding_mismatch")
		}
		if item.ToolCallID == nil {
			return errors.New("runtime_check_receipt_binding_mismatch")
		}
		callID := *item.ToolCallID
		want, ok := expected[callID]
		if !ok || item.Action != want {
			return errors.New("runtime_check_receipt_action_mismatch")
		}
		switch item.RecordType {
		case "decision":
			if _, exists := decisions[callID]; exists {
				return errors.New("runtime_check_receipt_duplicate")
			}
			if want == "allow" && (item.Tool != "read_file" || item.MatchedGrantID == nil || *item.MatchedGrantID != r.record.GrantID || item.AuthorityStatus != "valid") {
				return errors.New("runtime_check_receipt_binding_mismatch")
			}
			if want == "deny" && item.Tool != "write_file" {
				return errors.New("runtime_check_receipt_action_mismatch")
			}
			decisions[callID] = item
		case "observation":
			decision, exists := decisions[callID]
			if want != "allow" || !exists || item.DecisionReceiptID != decision.ReceiptID || item.ActionID != decision.ActionID {
				return errors.New("runtime_check_receipt_correlation_mismatch")
			}
		default:
			return errors.New("runtime_check_receipt_type_invalid")
		}
		counts[callID]++
		if counts[callID] > 2 || want == "deny" && counts[callID] > 1 {
			return errors.New("runtime_check_receipt_duplicate")
		}
		r.record.Result.ReceiptIDs = append(r.record.Result.ReceiptIDs, item.ReceiptID)
	}
	if counts["rc-first"] != 2 || counts["rc-denied"] != 1 || counts["rc-last"] != 2 {
		return errors.New("runtime_check_receipts_missing")
	}
	r.record.Result.Checks = map[string]bool{"native_session_bound": true, "allowed_read": true, "write_denied_before_execution": true, "allowed_after_denial": true, "receipt_chain_verified": true}
	return nil
}
