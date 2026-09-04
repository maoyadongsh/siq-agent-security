package server

import (
	"net/http"
	"os"
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
)

func (s *Server) adapterStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	writeJSON(w, 200, map[string]any{
		"detected":  adapterinstall.Detect(s.d.Home),
		"platforms": s.platforms(),
	})
}

func (s *Server) adapterInstall(w http.ResponseWriter, r *http.Request) {
	s.adapterMutate(w, r, "install")
}

func (s *Server) adapterUninstall(w http.ResponseWriter, r *http.Request) {
	s.adapterMutate(w, r, "uninstall")
}

func (s *Server) adapterMutate(w http.ResponseWriter, r *http.Request, action string) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		Platform string `json:"platform"`
	}
	if err := readJSON(r, &body, 16<<10); err != nil || body.Platform == "" {
		writeJSON(w, 400, map[string]any{"error": "platform required"})
		return
	}
	bin := s.d.Binary
	if bin == "" {
		exe, err := os.Executable()
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "binary path unavailable"})
			return
		}
		bin, _ = filepath.Abs(exe)
	}
	ep := s.d.Endpoint
	if ep == "" {
		ep = "http://127.0.0.1:47611"
	}
	opts := adapterinstall.Options{
		Platform: body.Platform, Home: s.d.Home, StateDir: s.d.Store.Dir,
		Binary: bin, Endpoint: ep, Mode: s.currentMode(),
	}
	var (
		res *adapterinstall.Result
		err error
	)
	switch action {
	case "install":
		res, err = adapterinstall.Install(opts)
	case "uninstall":
		res, err = adapterinstall.Uninstall(opts)
	default:
		writeJSON(w, 404, map[string]any{"error": "unknown action"})
		return
	}
	if err != nil {
		writeJSON(w, 400, map[string]any{"error": err.Error()})
		return
	}
	writeJSON(w, 200, res)
}
