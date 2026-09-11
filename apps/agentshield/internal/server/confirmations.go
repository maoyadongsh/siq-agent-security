package server

import (
	"errors"
	"net/http"
	"strings"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func (s *Server) confirmations(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	writeJSON(w, 200, s.d.Engine.Confirmations())
}
func (s *Server) confirmationResolve(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	path := strings.TrimPrefix(r.URL.Path, "/v1/confirmations/")
	id, suffix, found := strings.Cut(path, "/")
	if !found || id == "" || suffix != "resolve" {
		w.WriteHeader(404)
		return
	}
	var body receipt.ConfirmationResolve
	if !readRuntimeIdentity(w, r, &body, "schema_version", "decision_receipt_id", "decision_hash", "params_digest", "approve", "actor_id") {
		return
	}
	rec, err := s.d.Engine.ResolveConfirmation(id, body)
	if err != nil {
		status, code := 503, "confirmation_unavailable"
		switch {
		case errors.Is(err, receipt.ErrConfirmationInvalid):
			status, code = 400, "confirmation_invalid_request"
		case errors.Is(err, receipt.ErrConfirmationConflict), errors.Is(err, receipt.ErrHoldExpired), errors.Is(err, receipt.ErrHoldConflict):
			status, code = 409, "confirmation_changed_or_resolved"
		default:
			var correlation *receipt.CorrelationError
			if errors.As(err, &correlation) {
				status, code = 409, "confirmation_authority_changed"
			}
		}
		writeJSON(w, status, map[string]string{"error": code})
		return
	}
	s.invalidateProjection("confirmation_resolved")
	writeJSON(w, 200, map[string]string{"receipt_id": rec.ReceiptID, "action": rec.Action})
}
