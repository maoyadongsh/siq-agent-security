package receipt

import (
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
	"time"
)

func (e *Engine) checkContext(req Request, taskID string, now time.Time) error {
	if req.ContextAssertionID == "" {
		return nil
	}
	if e.opts.ContextLookup == nil || taskID == "" {
		return &trustedcontext.Violation{Code: "trusted_context_invalid"}
	}
	a, err := e.opts.ContextLookup(req.ContextAssertionID)
	if err != nil {
		return err
	}
	if a == nil || a.AssertionID != req.ContextAssertionID {
		return &trustedcontext.Violation{Code: "trusted_context_invalid"}
	}
	return a.Check(trustedcontext.Subject{Platform: req.Platform, SessionID: req.SessionID, AgentID: req.AgentID}, taskID, req.Tool, req.ToolCallID, req.Params, now)
}
