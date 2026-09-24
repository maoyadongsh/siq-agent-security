package server

import (
	"encoding/json"
	"io"
	"net/http"
	"time"
)

func (s *Server) openshellTargets(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	if r.URL.RawQuery != "" {
		writeJSON(w, 400, map[string]string{"error": "openshell_target_request_invalid"})
		return
	}
	// Multiple bounded CLI reads can exceed the default response write budget.
	if http.NewResponseController(w).SetWriteDeadline(time.Now().Add(120*time.Second)) != nil {
		writeJSON(w, 503, map[string]string{"error": "openshell_discovery_deadline_unavailable"})
		return
	}
	writeJSON(w, 200, s.d.Openshell.DiscoverTargets())
}

func (s *Server) openshellTargetInspect(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		Schema      string `json:"schema_version"`
		ID          string `json:"sandbox_id"`
		Name        string `json:"name"`
		Fingerprint string `json:"endpoint_fingerprint"`
	}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8192))
	decoder.DisallowUnknownFields()
	var trailing any
	if r.URL.RawQuery != "" || decoder.Decode(&body) != nil || decoder.Decode(&trailing) != io.EOF || body.Schema != "local-openshell-target-inspect/v1" {
		writeJSON(w, 400, map[string]string{"error": "openshell_target_request_invalid"})
		return
	}
	if http.NewResponseController(w).SetWriteDeadline(time.Now().Add(180*time.Second)) != nil {
		writeJSON(w, 503, map[string]string{"error": "openshell_discovery_deadline_unavailable"})
		return
	}
	out, err := s.d.Openshell.InspectDiscoveredTarget(body.ID, body.Name, body.Fingerprint)
	if err != nil {
		writeJSON(w, 409, map[string]string{"error": "openshell_target_readback_unavailable"})
		return
	}
	writeJSON(w, 200, out)
}
