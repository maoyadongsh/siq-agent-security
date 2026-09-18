package server

import (
	"errors"
	"net/http"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func (s *Server) holdExecutionReserve(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body receipt.HoldExecutionReserve
	if err := readJSONStrict(r, &body, 4<<20); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	status, err := s.d.Engine.ReserveHoldExecution(body)
	if err != nil {
		code := http.StatusBadRequest
		switch {
		case errors.Is(err, receipt.ErrHoldExecutionConflict):
			code = http.StatusConflict
		case errors.Is(err, receipt.ErrHoldExpired):
			code = http.StatusGone
		}
		var correlation *receipt.CorrelationError
		reason := err.Error()
		if errors.As(err, &correlation) {
			reason = correlation.Code
		}
		writeJSON(w, code, map[string]string{"error": reason, "reason_code": reason})
		return
	}
	writeJSON(w, http.StatusCreated, status)
}

func (s *Server) holdExecutionStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body receipt.HoldExecutionStatusRequest
	if err := readJSONStrict(r, &body, 4<<20); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	status, err := s.d.Engine.ReadHoldExecutionStatus(body)
	if err != nil {
		var correlation *receipt.CorrelationError
		reason := err.Error()
		if errors.As(err, &correlation) {
			reason = correlation.Code
		}
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": reason, "reason_code": reason})
		return
	}
	writeJSON(w, http.StatusOK, status)
}

func (s *Server) holdExecutionReconcile(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body receipt.HoldExecutionReconcile
	if err := readJSONStrict(r, &body, 64<<10); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	status, err := s.d.Engine.ReconcileHoldExecution(body)
	if err != nil {
		code := http.StatusServiceUnavailable
		reason := "hold_reconciliation_unavailable"
		switch {
		case errors.Is(err, receipt.ErrHoldReconciliationInvalid):
			code, reason = http.StatusBadRequest, err.Error()
		case errors.Is(err, receipt.ErrHoldReconciliationConflict):
			code, reason = http.StatusConflict, err.Error()
		case errors.Is(err, receipt.ErrHoldExpired):
			code, reason = http.StatusGone, "hold_reconciliation_window_expired"
		}
		writeJSON(w, code, map[string]string{"error": reason, "reason_code": reason})
		return
	}
	s.invalidateProjection("hold_execution_reconciled")
	writeJSON(w, http.StatusOK, status)
}
