package server

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/modelconfig"
)

func (s *Server) modelTargets() ([]modelconfig.Target, bool) {
	roots := hermeshome.Scan(s.hermesRoots())
	out := []modelconfig.Target{}
	partial := len(roots.Issues) > 0
	for _, root := range roots.Roots {
		if root.Detected {
			out = append(out, modelconfig.Discover(modelconfig.Source{ID: root.ID, Name: root.Name, Root: root.Path, Platform: "hermes"})...)
		}
	}
	home := s.hermesRoots().Home
	root := adapterinstall.DefaultConfigDir(home, adapterinstall.OpenClaw)
	if st, err := os.Lstat(root); err == nil && st.IsDir() {
		out = append(out, modelconfig.Discover(modelconfig.Source{ID: hermeshome.Identifier(root), Name: "default", Root: filepath.Clean(root), Platform: "openclaw"})...)
	} else if !os.IsNotExist(err) {
		partial = true
	}
	return out, partial
}
func (s *Server) modelConnections(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	if r.URL.RawQuery != "" {
		writeJSON(w, 400, map[string]string{"error": "model_connection_request_invalid"})
		return
	}
	targets, partial := s.modelTargets()
	items := []modelconfig.Item{}
	for _, t := range targets {
		items = append(items, t.Item)
	}
	writeJSON(w, 200, map[string]any{"schema_version": "local-model-connections/v1", "observed_at": time.Now().UTC().Format(time.RFC3339Nano), "items": items, "partial": partial, "network_requested": false})
}
func (s *Server) modelConnectionCheck(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		Schema      string `json:"schema_version"`
		ID          string `json:"id"`
		Fingerprint string `json:"fingerprint"`
	}
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096))
	d.DisallowUnknownFields()
	var trailing any
	if r.URL.RawQuery != "" || d.Decode(&body) != nil || d.Decode(&trailing) != io.EOF || body.Schema != "local-model-connection-check/v1" {
		writeJSON(w, 400, map[string]string{"error": "model_connection_request_invalid"})
		return
	}
	targets, _ := s.modelTargets()
	for _, target := range targets {
		if target.Item.ID != body.ID || target.Item.Fingerprint != body.Fingerprint || !target.Item.CanCheck {
			continue
		}
		result := modelconfig.Check(r.Context(), target)
		after, _ := s.modelTargets()
		for _, t := range after {
			if t.Item.ID == target.Item.ID && t.Item.Fingerprint == target.Item.Fingerprint && t.Item.CanCheck {
				writeJSON(w, 200, result)
				return
			}
		}
		break
	}
	writeJSON(w, 409, map[string]string{"error": "model_configuration_changed"})
}
