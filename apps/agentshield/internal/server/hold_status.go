package server

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

func (s *Server) holdStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]string{"error": "POST required"})
		return
	}
	var body receipt.HoldStatusRequest
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<20))
	decoder.UseNumber()
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&body); err != nil {
		writeJSON(w, 400, map[string]string{"error": "invalid request"})
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		writeJSON(w, 400, map[string]string{"error": "invalid request"})
		return
	}
	status, err := s.d.Engine.ReadHoldStatus(body)
	if err != nil {
		var correlation *receipt.CorrelationError
		if errors.As(err, &correlation) {
			writeJSON(w, 400, map[string]string{"error": correlation.Code, "reason_code": correlation.Code})
		} else {
			writeJSON(w, 500, map[string]string{"error": "hold status unavailable"})
		}
		return
	}
	writeJSON(w, 200, status)
}
