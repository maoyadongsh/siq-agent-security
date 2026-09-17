package receipt

// RecheckReservedExecution is a final check by the original in-process consumer
// immediately before its first side effect. It neither reserves nor licenses a
// replay; an uncertain reservation must never be resumed using this check alone.
func (e *Engine) RecheckReservedExecution(req HoldExecutionStatusRequest) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	a := e.actions[req.ActionID]
	if !validateExecutionStatusRequest(req, a) || a.reservation == nil || a.observation != nil || a.reconciliation != nil {
		return ErrHoldExecutionConflict
	}
	now := e.opts.Now()
	deadline, err := holdExecutionDeadline(a.decision)
	if err != nil || !now.Before(deadline) || !now.Before(a.expires) {
		return ErrHoldExpired
	}
	original := HoldStatusRequest{Platform: req.Platform, SessionID: req.SessionID, AgentID: req.AgentID, TaskID: req.TaskID, RuntimeTaskID: req.RuntimeTaskID, Tool: req.Tool, ToolCallID: str(a.decision.ToolCallID), ActionID: req.ActionID, DecisionReceiptID: req.DecisionReceiptID, Params: req.Params}
	if !e.holdAuthorityCurrent(original, a.decision, now) {
		return correlationError("hold_authority_changed")
	}
	return nil
}
