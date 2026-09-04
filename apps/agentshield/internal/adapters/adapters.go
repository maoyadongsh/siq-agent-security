// Package adapters holds the host-side halves of platform adapters that run as
// agentshield subcommands (dev-spec §4): OpenClaw's operator install policy
// (`agentshield policy-exec`) and CodeBuddy's PreToolUse hook
// (`agentshield hook codebuddy`). They translate platform I/O contracts to
// admission / decision calls and apply the fail-closed table; no policy lives here.
package adapters

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"strings"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// ---------------------------------------------------------------- OpenClaw

// PolicyExecRequest is the subset of OpenClaw's security.installPolicy stdin
// document we rely on (docs 2026-09: targetType, staged path, optional
// skill.installSpec). Unknown fields are ignored.
type PolicyExecRequest struct {
	TargetType string `json:"targetType"`
	Target     struct {
		Name string `json:"name"`
	} `json:"target"`
	Source struct {
		Kind    string `json:"kind"`
		Locator string `json:"locator"`
	} `json:"source"`
	StagedPath string `json:"stagedPath"`
	Skill      *struct {
		InstallID   string          `json:"installId"`
		InstallSpec json.RawMessage `json:"installSpec"`
	} `json:"skill"`
}

// PolicyExecResponse is OpenClaw's expected stdout: decision allow|warn|block.
type PolicyExecResponse struct {
	Decision    string `json:"decision"`
	Reason      string `json:"reason"`
	AdmissionID string `json:"admissionId,omitempty"`
	Verdict     string `json:"verdict,omitempty"`
}

// PolicyExecDeps are what the install policy needs.
type PolicyExecDeps struct {
	Pack    *rulepack.Pack
	Key     *signing.Key
	Version string
	Persist func(*admission.Result) error // optional: store admission + card
}

// PolicyExec reads one request and returns the decision. Any failure to
// analyse is block (OpenClaw itself fails closed when the exec errors, so we
// keep the contract symmetric).
func PolicyExec(in io.Reader, d PolicyExecDeps) PolicyExecResponse {
	var req PolicyExecRequest
	if err := json.NewDecoder(in).Decode(&req); err != nil {
		return PolicyExecResponse{Decision: "block", Reason: "agentshield: malformed install policy request"}
	}
	if req.TargetType != "" && req.TargetType != "skill" {
		return PolicyExecResponse{Decision: "warn", Reason: "agentshield: only skill targets are analysed; plugin installs are not covered by this policy"}
	}
	if req.StagedPath == "" {
		return PolicyExecResponse{Decision: "block", Reason: "agentshield: no staged path to analyse"}
	}
	st, err := os.Stat(req.StagedPath)
	if err != nil || !st.IsDir() {
		return PolicyExecResponse{Decision: "block", Reason: "agentshield: staged path is not a readable directory"}
	}
	trust := "unknown"
	if strings.Contains(strings.ToLower(req.Source.Kind), "clawhub") {
		trust = "community"
	}
	res, err := admission.Admit(req.StagedPath, admission.Options{
		Source:  admission.Source{Type: "marketplace", Locator: firstNonEmpty(req.Source.Locator, req.Target.Name, req.StagedPath), TrustLevel: trust},
		Version: d.Version, Key: d.Key, Pack: d.Pack,
	})
	if err != nil {
		return PolicyExecResponse{Decision: "block", Reason: "agentshield: admission failed (fail-closed)"}
	}
	if d.Persist != nil {
		_ = d.Persist(res)
	}
	out := PolicyExecResponse{AdmissionID: res.Admission.AdmissionID, Verdict: res.Admission.Verdict}
	switch res.Admission.Verdict {
	case "admit":
		out.Decision, out.Reason = "allow", "agentshield: no capability declarations or threats found"
	case "admit_with_conditions":
		out.Decision = "warn"
		out.Reason = "agentshield: skill declares " + itoa(len(res.Admission.DeclaredFacts)) + " capabilities; run `agentshield grant " + res.Admission.AdmissionID + "` before use"
	default:
		out.Decision = "block"
		out.Reason = "agentshield: quarantined (" + quarantineSummary(res.Admission) + ")"
	}
	return out
}

func quarantineSummary(a admission.Admission) string {
	seen := map[string]bool{}
	var parts []string
	for _, f := range a.Findings {
		if f.Disposition == "quarantine" && !seen[f.Category] {
			seen[f.Category] = true
			parts = append(parts, f.Category)
		}
	}
	if len(parts) == 0 {
		return "integrity"
	}
	return strings.Join(parts, ", ")
}

// ---------------------------------------------------------------- CodeBuddy

// CodeBuddyInput is the PreToolUse / PostToolUse stdin document.
type CodeBuddyInput struct {
	SessionID      string         `json:"session_id"`
	Cwd            string         `json:"cwd"`
	PermissionMode string         `json:"permission_mode"`
	HookEventName  string         `json:"hook_event_name"`
	ToolName       string         `json:"tool_name"`
	ToolInput      map[string]any `json:"tool_input"`
	ToolResponse   any            `json:"tool_response"`
}

// CodeBuddyOutput is the hookSpecificOutput contract.
type CodeBuddyOutput struct {
	HookSpecificOutput struct {
		HookEventName            string `json:"hookEventName"`
		PermissionDecision       string `json:"permissionDecision,omitempty"`
		PermissionDecisionReason string `json:"permissionDecisionReason,omitempty"`
	} `json:"hookSpecificOutput"`
}

// Decider abstracts the decision service (HTTP client in the CLI, engine in tests).
type Decider interface {
	Decide(receipt.Request) (*receipt.Decision, error)
	Observe(receipt.Request, string) error
}

// CodeBuddyHook maps one hook event. mode is the enforcement mode used for the
// fail-closed table when the decider errors.
func CodeBuddyHook(in io.Reader, d Decider, agentID, mode string) (CodeBuddyOutput, error) {
	var out CodeBuddyOutput
	var ev CodeBuddyInput
	if err := json.NewDecoder(in).Decode(&ev); err != nil {
		return failClosed(out, "PreToolUse", mode, "malformed hook input")
	}
	out.HookSpecificOutput.HookEventName = ev.HookEventName
	req := receipt.Request{Platform: "codebuddy", SessionID: firstNonEmpty(ev.SessionID, "codebuddy-default"), AgentID: agentID,
		Tool: ev.ToolName, Params: ev.ToolInput, Context: map[string]any{"cwd": ev.Cwd, "permission_mode": ev.PermissionMode}}
	switch ev.HookEventName {
	case "PostToolUse":
		text := ""
		switch t := ev.ToolResponse.(type) {
		case string:
			text = t
		case nil:
		default:
			b, _ := json.Marshal(t)
			text = string(b)
		}
		if len(text) > 64<<10 {
			text = text[:64<<10]
		}
		_ = d.Observe(req, text) // observation only; never blocks
		return out, nil
	case "PreToolUse", "":
		out.HookSpecificOutput.HookEventName = "PreToolUse"
		dec, err := d.Decide(req)
		if err != nil || dec == nil {
			return failClosed(out, "PreToolUse", mode, "decision service unavailable")
		}
		switch dec.Action {
		case receipt.ActionAllow:
			out.HookSpecificOutput.PermissionDecision = "allow"
		case receipt.ActionDeny:
			out.HookSpecificOutput.PermissionDecision = "deny"
		case receipt.ActionHold, receipt.ActionRedact: // CodeBuddy cannot rewrite params → ask
			out.HookSpecificOutput.PermissionDecision = "ask"
		default:
			return failClosed(out, "PreToolUse", mode, "malformed decision")
		}
		out.HookSpecificOutput.PermissionDecisionReason = "AgentShield: " + dec.Reason + " (receipt " + dec.Receipt.ReceiptID + ")"
		return out, nil
	}
	return out, errors.New("unsupported hook event " + ev.HookEventName)
}

func failClosed(out CodeBuddyOutput, event, mode, reason string) (CodeBuddyOutput, error) {
	out.HookSpecificOutput.HookEventName = event
	if mode == "block" {
		out.HookSpecificOutput.PermissionDecision = "deny"
		out.HookSpecificOutput.PermissionDecisionReason = "AgentShield: " + reason + "; blocked (fail-closed)"
	} else {
		out.HookSpecificOutput.PermissionDecision = "allow"
		out.HookSpecificOutput.PermissionDecisionReason = "AgentShield: " + reason + "; allowed in " + mode + " mode"
	}
	return out, nil
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

func itoa(i int) string {
	b, _ := json.Marshal(i)
	return string(b)
}
