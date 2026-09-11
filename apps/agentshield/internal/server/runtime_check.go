package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/runtimecheck"
)

func (s *Server) initRuntimeChecks() error {
	var err error
	s.runtimeChecks, err = runtimecheck.New(runtimecheck.Options{Store: s.d.Store, Intents: s.intents, Key: s.d.Key, Pack: s.d.Pack, Chain: s.d.Chain, Endpoint: s.adapterOptions(adapterinstall.Hermes).Endpoint,
		Snapshot: func(id string) (adapterinstall.RuntimeTarget, error) {
			opts, err := s.resolveAdapterOptions(adapterinstall.Hermes, id)
			if err != nil {
				return adapterinstall.RuntimeTarget{}, errors.New("runtime_check_instance_unavailable")
			}
			opts.NativeCLI = s.d.HermesCLI
			return adapterinstall.InspectRuntimeTarget(opts)
		}})
	return err
}
func (s *Server) CloseRuntimeChecks(ctx context.Context) error {
	if s.runtimeChecks == nil {
		return nil
	}
	return s.runtimeChecks.Close(ctx)
}

func (s *Server) runtimeCheckLatest(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	items, err := s.runtimeChecks.Latest(r.URL.Query().Get("instance_id"))
	if err != nil {
		runtimeCheckError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"schema_version": "local-runtime-check-list/v1", "items": items})
}
func readRuntimeCheck(w http.ResponseWriter, r *http.Request, body any) bool {
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10))
	decoder.DisallowUnknownFields()
	decoder.UseNumber()
	var extra any
	if decoder.Decode(body) != nil || decoder.Decode(&extra) != io.EOF {
		writeJSON(w, 400, map[string]string{"error": "runtime_check_invalid_request"})
		return false
	}
	return true
}
func runtimeCheckError(w http.ResponseWriter, err error) {
	code := err.Error()
	if !strings.HasPrefix(code, "runtime_check_") {
		code = "runtime_check_unavailable"
	}
	status := 500
	switch {
	case errors.Is(err, runtimecheck.ErrNotFound), code == "runtime_check_instance_unavailable":
		status = 404
	case errors.Is(err, runtimecheck.ErrCredential):
		status = 403
	case errors.Is(err, runtimecheck.ErrConflict), strings.Contains(code, "changed"), strings.Contains(code, "not_ready"), strings.Contains(code, "cleanup_required"):
		status = 409
	case strings.Contains(code, "capacity"):
		status = 429
	case code == "runtime_check_invalid_request" || code == "runtime_check_invalid_actor":
		status = 400
	}
	writeJSON(w, status, map[string]string{"error": code})
}
func (s *Server) runtimeCheckPreview(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		SchemaVersion string `json:"schema_version"`
		InstanceID    string `json:"instance_id"`
	}
	if !readRuntimeCheck(w, r, &body) {
		return
	}
	if body.SchemaVersion != "local-runtime-check-preview/v1" {
		runtimeCheckError(w, errors.New("runtime_check_invalid_request"))
		return
	}
	plan, err := s.runtimeChecks.Preview(body.InstanceID, r.Header.Get("Authorization"))
	if err != nil {
		runtimeCheckError(w, err)
		return
	}
	writeJSON(w, 200, plan)
}
func (s *Server) runtimeCheckStart(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		SchemaVersion string `json:"schema_version"`
		ID            string `json:"check_id"`
		Digest        string `json:"plan_digest"`
		Actor         string `json:"actor_id"`
		Confirm       bool   `json:"confirm"`
	}
	if !readRuntimeCheck(w, r, &body) {
		return
	}
	if body.SchemaVersion != "local-runtime-check-start/v1" || !body.Confirm {
		runtimeCheckError(w, errors.New("runtime_check_invalid_request"))
		return
	}
	out, err := s.runtimeChecks.Start(body.ID, body.Digest, r.Header.Get("Authorization"), body.Actor)
	if err != nil {
		runtimeCheckError(w, err)
		return
	}
	writeJSON(w, 202, out)
}
func (s *Server) runtimeCheckAttach(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body runtimecheck.Attach
	if !readRuntimeCheck(w, r, &body) {
		return
	}
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(auth, "Bearer ") {
		runtimeCheckError(w, runtimecheck.ErrCredential)
		return
	}
	out, err := s.runtimeChecks.Attach(body, strings.TrimPrefix(auth, "Bearer "))
	if err != nil {
		runtimeCheckError(w, err)
		return
	}
	writeJSON(w, 200, out)
}
func (s *Server) runtimeCheckOne(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	id := strings.TrimPrefix(r.URL.Path, "/v1/runtime-checks/")
	var out runtimecheck.Result
	var err error
	if strings.HasSuffix(id, "/cleanup") {
		if r.Method != http.MethodPost {
			w.WriteHeader(405)
			return
		}
		out, err = s.runtimeChecks.RetryCleanup(strings.TrimSuffix(id, "/cleanup"))
	} else if strings.HasSuffix(id, "/cancel") {
		if r.Method != http.MethodPost {
			w.WriteHeader(405)
			return
		}
		out, err = s.runtimeChecks.Cancel(strings.TrimSuffix(id, "/cancel"))
	} else {
		if r.Method != http.MethodGet {
			w.WriteHeader(405)
			return
		}
		out, err = s.runtimeChecks.Get(id)
	}
	if err != nil {
		runtimeCheckError(w, err)
		return
	}
	writeJSON(w, 200, out)
}
