package adapters

import (
	"crypto/sha256"
	"encoding/hex"
	"io"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/pending"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

func WorkBuddyManagedBootstrapFailure(in io.Reader, mode, stateDir, code string) WorkBuddyOutput {
	ev, err := ParseWorkBuddyManagedInput(in)
	if err != nil {
		return workBuddyLocalFailure(nil, mode, stateDir, "parse", "workbuddy_input_invalid", "invalid managed hook input")
	}
	return workBuddyLocalFailure(&ev, mode, stateDir, "bootstrap", code, "managed configuration or credential unavailable; run adapter diagnosis (workbuddy-preflight)")
}

// ev must come from the strict managed parser. Never persist tool parameters or
// use local correlation fields as proof of an online service decision.
func workBuddyLocalFailure(ev *WorkBuddyManagedInput, mode, stateDir, stage, code, reason string) WorkBuddyOutput {
	if mode != "block" && mode != "warn" && mode != "audit_only" {
		mode = "block"
	}
	rec := pending.Record{Schema: pending.LocalSchemaID, Platform: "workbuddy", EnforcementMode: mode, Outcome: "deny", Reason: reason, Origin: "local_hook", Stage: stage, ReasonCode: code}
	var out WorkBuddyOutput
	out.HookSpecificOutput.HookEventName = "PreToolUse"
	if ev != nil {
		out.HookSpecificOutput.HookEventName = ev.HookEventName
		session, se := runtimeidentity.WorkBuddySessionID(ev.SessionID)
		call, ce := runtimeidentity.WorkBuddyCallID(ev.SessionID, ev.CallID)
		raw, err := canon.Marshal(map[string]any{"session_id": session, "tool_call_id": call, "tool": ev.ToolName, "params": ev.ToolInput})
		if se == nil && ce == nil && err == nil {
			digest := sha256.Sum256(append([]byte("workbuddy-local-action/v1\x00"), raw...))
			rec.Tool, rec.SessionID, rec.ToolCallID = ev.ToolName, session, call
			rec.NativeSessionID, rec.NativeCallID, rec.ActionDigest = ev.SessionID, ev.CallID, hex.EncodeToString(digest[:])
		}
	}
	if out.HookSpecificOutput.HookEventName == "PostToolUse" {
		rec.Stage, rec.Outcome = "observation", "unconfirmed"
		out.HookSpecificOutput.PermissionDecisionReason = product.Name + ": managed observation unavailable; no receipt confirmed"
	} else {
		out.HookSpecificOutput.PermissionDecision = "deny"
		out.HookSpecificOutput.PermissionDecisionReason = product.Name + ": " + reason + "; blocked (fail-closed)"
	}
	_ = pending.Append(stateDir, rec)
	return out
}
