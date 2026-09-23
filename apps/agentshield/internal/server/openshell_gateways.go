package server

import (
	"encoding/json"
	"io"
	"net/http"
	"regexp"
	"time"
)

var gatewaySelectionID = regexp.MustCompile(`^og-[0-9a-f]{32}$`)
var gatewaySelectionFingerprint = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (s *Server) openshellGateways(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	if r.URL.RawQuery != "" {
		writeJSON(w, 400, map[string]string{"error": "openshell_gateway_request_invalid"})
		return
	}
	if http.NewResponseController(w).SetWriteDeadline(time.Now().Add(120*time.Second)) != nil {
		writeJSON(w, 503, map[string]string{"error": "openshell_discovery_deadline_unavailable"})
		return
	}
	writeJSON(w, 200, s.d.Openshell.DiscoverGateways())
}

func (s *Server) openshellSelectedGateway(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	inspect := r.URL.Path == "/v1/openshell/gateways/inspect"
	fields := []string{"schema_version", "gateway_id", "configuration_fingerprint"}
	schema := "local-openshell-gateway-select/v1"
	if inspect {
		fields = append(fields, "sandbox_id", "name", "endpoint_fingerprint")
		schema = "local-openshell-gateway-inspect/v1"
	}
	var body struct {
		Schema      string `json:"schema_version"`
		ID          string `json:"gateway_id"`
		Fingerprint string `json:"configuration_fingerprint"`
		Target      string `json:"sandbox_id"`
		Name        string `json:"name"`
		EndpointFP  string `json:"endpoint_fingerprint"`
	}
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 8192))
	if err != nil || r.URL.RawQuery != "" || !exactJSONObject(raw, fields...) || json.Unmarshal(raw, &body) != nil || body.Schema != schema || !gatewaySelectionID.MatchString(body.ID) || !gatewaySelectionFingerprint.MatchString(body.Fingerprint) {
		writeJSON(w, 400, map[string]string{"error": "openshell_gateway_request_invalid"})
		return
	}
	if http.NewResponseController(w).SetWriteDeadline(time.Now().Add(180*time.Second)) != nil {
		writeJSON(w, 503, map[string]string{"error": "openshell_discovery_deadline_unavailable"})
		return
	}
	if inspect {
		out, err := s.d.Openshell.InspectRegisteredGateway(body.ID, body.Fingerprint, body.Target, body.Name, body.EndpointFP)
		if err != nil {
			writeJSON(w, 409, map[string]string{"error": "openshell_gateway_readback_unavailable"})
			return
		}
		writeJSON(w, 200, out)
		return
	}
	out, err := s.d.Openshell.RegisteredGatewayTargets(body.ID, body.Fingerprint)
	if err != nil {
		writeJSON(w, 409, map[string]string{"error": "openshell_gateway_selection_changed"})
		return
	}
	writeJSON(w, 200, out)
}
