package main

import (
	"errors"
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/workbuddycorrelation"
)

func workBuddyBlocked(reason string) (*receipt.Decision, error) {
	return nil, &adapters.WorkBuddyManagedFailure{Uncertain: strings.Contains(reason, "uncertain") || strings.Contains(reason, "do not replay")}
}

func (h *workBuddyManagedClient) Decide(req receipt.Request) (*receipt.Decision, error) {
	tx, err := workbuddycorrelation.Lock(h.config, req)
	if err != nil {
		return workBuddyBlocked(err.Error())
	}
	defer tx.Close()
	prior, err := tx.PriorHold()
	if err != nil {
		return workBuddyBlocked(err.Error())
	}
	if err = tx.Write("pre", tx.Base); err != nil {
		return workBuddyBlocked("duplicate or unavailable pre correlation; blocked")
	}
	if h.ctx.Err() != nil {
		return workBuddyBlocked("request deadline elapsed; execution uncertain")
	}
	if prior != nil {
		return h.resumeWorkBuddy(tx, req, *prior)
	}
	d, err := h.requestDecision(req)
	if err != nil {
		return workBuddyBlocked("decision response unavailable; execution uncertain; do not replay")
	}
	outcome := d.Action
	if outcome == receipt.ActionRedact {
		outcome = receipt.ActionDeny
	}
	if err = tx.Write("decision", tx.Decision(outcome, d)); err != nil || h.ctx.Err() != nil {
		return workBuddyBlocked("decision correlation unavailable; execution uncertain; do not replay")
	}
	return d, nil
}

func (h *workBuddyManagedClient) resumeWorkBuddy(tx *workbuddycorrelation.Transaction, req receipt.Request, prior workbuddycorrelation.Record) (*receipt.Decision, error) {
	blocked := func(reason string) (*receipt.Decision, error) {
		_ = tx.Write("decision", tx.Decision("blocked", nil))
		return workBuddyBlocked(reason)
	}
	original := receipt.HoldStatusRequest{Platform: "workbuddy", SessionID: req.SessionID, AgentID: req.AgentID, Tool: req.Tool, ToolCallID: prior.ToolCallID, ActionID: prior.ActionID, DecisionReceiptID: prior.DecisionReceiptID, Params: req.Params, TaskID: prior.TaskID, RuntimeTaskID: prior.RuntimeTaskID}
	raw, err := h.post("/v1/hold-status", original)
	if err != nil {
		return blocked("approval status unavailable; blocked")
	}
	var status receipt.HoldStatus
	fields := []string{"schema_version", "status", "action_id", "decision_receipt_id", "expires_at", "reason_code"}
	if adapters.DecodeWorkBuddyObject(raw, fields, fields, &status) != nil || status.SchemaVersion != "hold-status/v1" || status.ActionID != prior.ActionID || status.DecisionReceiptID != prior.DecisionReceiptID {
		return blocked("approval status mismatch; blocked")
	}
	expires, err := time.Parse(time.RFC3339Nano, status.ExpiresAt)
	if err != nil {
		return blocked("approval time invalid; blocked")
	}
	if status.Status != "approved" || !time.Now().Before(expires) {
		if status.Status == "denied" || status.Status == "expired" {
			_ = tx.Write("terminal", prior)
		}
		if status.Status == "consumed" {
			return blocked("approval execution uncertain or consumed; do not replay")
		}
		return blocked("approval is pending, denied or expired; blocked")
	}
	// Claim before the request: neither a lost response nor another process can
	// turn a status read into another permission to execute.
	if err = tx.Write("consume", prior); err != nil {
		return blocked("approval execution uncertain; do not replay")
	}
	reserve := receipt.HoldExecutionReserve{SchemaVersion: "hold-execution-reserve/v1", Platform: "workbuddy", SessionID: req.SessionID, AgentID: req.AgentID, Tool: req.Tool, OriginalToolCallID: prior.ToolCallID, RetryToolCallID: req.ToolCallID, ActionID: prior.ActionID, DecisionReceiptID: prior.DecisionReceiptID, Params: req.Params, TaskID: prior.TaskID, RuntimeTaskID: prior.RuntimeTaskID}
	raw, err = h.postStatus("/v1/hold-executions/reserve", reserve, http.StatusCreated)
	if err != nil {
		return blocked("approval reservation response unavailable; execution uncertain; do not replay")
	}
	var reserved receipt.HoldExecutionStatus
	fields = []string{"schema_version", "status", "action_id", "decision_receipt_id", "reservation_receipt_id", "expires_at", "reason_code"}
	if adapters.DecodeWorkBuddyObject(raw, fields, fields, &reserved) != nil || reserved.SchemaVersion != "hold-execution-status/v1" || reserved.Status != "reserved" || reserved.ActionID != prior.ActionID || reserved.DecisionReceiptID != prior.DecisionReceiptID || reserved.ReservationReceiptID == "" || reserved.ReservationReceiptID == prior.DecisionReceiptID || reserved.ReasonCode != "hold_execution_reserved" {
		return blocked("approval reservation mismatch; execution uncertain; do not replay")
	}
	expires, err = time.Parse(time.RFC3339Nano, reserved.ExpiresAt)
	localExpiry, _ := time.Parse(time.RFC3339Nano, prior.ExpiresAt)
	if err != nil || !time.Now().Before(expires) || !time.Now().Before(localExpiry) || h.ctx.Err() != nil {
		return blocked("approval reservation expired; execution uncertain; do not replay")
	}
	d := &receipt.Decision{Action: receipt.ActionAllow, Reason: "approved hold execution reserved", Receipt: receipt.Receipt{ReceiptID: reserved.ReservationReceiptID, ActionID: prior.ActionID, TaskID: prior.TaskID, RuntimeTaskID: prior.RuntimeTaskID, AuthorityStatus: "valid", EffectiveAction: receipt.ActionAllow}}
	r := tx.Decision("reserved", d)
	r.OriginalToolCallID = prior.ToolCallID
	r.OriginalDecisionReceiptID = prior.DecisionReceiptID
	if err = tx.Write("decision", r); err != nil || h.ctx.Err() != nil {
		return workBuddyBlocked("reserved execution correlation unavailable; execution uncertain; do not replay")
	}
	return d, nil
}

func (h *workBuddyManagedClient) Observe(req receipt.Request, result string) error {
	tx, err := workbuddycorrelation.Lock(h.config, req)
	if err != nil {
		return err
	}
	defer tx.Close()
	if _, err = tx.Read("pre", req.ToolCallID); err != nil {
		return workbuddycorrelation.ErrUnavailable
	}
	d, err := tx.Read("decision", req.ToolCallID)
	if err != nil || (d.Outcome != "allow" && d.Outcome != "reserved") {
		return workbuddycorrelation.ErrUnavailable
	}
	expires, err := time.Parse(time.RFC3339Nano, d.ExpiresAt)
	if err != nil || !time.Now().Before(expires) || h.ctx.Err() != nil {
		return workbuddycorrelation.ErrUncertain
	}
	if err = tx.Write("post", d); err != nil {
		return workbuddycorrelation.ErrUncertain
	}
	req.ActionID = d.ActionID
	req.DecisionReceiptID = d.DecisionReceiptID
	req.TaskID = d.TaskID
	req.RuntimeTaskID = d.RuntimeTaskID
	if err = h.requestObservation(req, result); err != nil {
		return workbuddycorrelation.ErrUncertain
	}
	if err = tx.Write("complete", d); err != nil {
		return err
	}
	if d.Outcome == "reserved" {
		original, err := tx.Read("decision", d.OriginalToolCallID)
		if err != nil || original.DecisionReceiptID != d.OriginalDecisionReceiptID || original.ActionID != d.ActionID {
			return errors.New("original hold correlation unavailable")
		}
		if err = tx.Write("terminal", original); err != nil {
			return err
		}
	}
	return nil
}
