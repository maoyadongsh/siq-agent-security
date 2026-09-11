package server

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// All fields in these flat request contracts are required, exact-case, non-null.
func readRuntimeIdentity(w http.ResponseWriter, r *http.Request, out any, fields ...string) bool {
	return readStrictFlatRequest(w, r, out, "runtime_identity_invalid_request", fields...)
}
func readStrictFlatRequest(w http.ResponseWriter, r *http.Request, out any, errorCode string, fields ...string) bool {
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 16<<10))
	fail := func() bool {
		writeJSON(w, 400, map[string]string{"error": errorCode})
		return false
	}
	if err != nil {
		return fail()
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	first, err := dec.Token()
	if err != nil || first != json.Delim('{') {
		return fail()
	}
	required := map[string]bool{}
	for _, field := range fields {
		required[field] = true
	}
	for dec.More() {
		key, e := dec.Token()
		if e != nil {
			return fail()
		}
		name, ok := key.(string)
		if !ok || !required[name] {
			return fail()
		}
		delete(required, name)
		var value json.RawMessage
		if dec.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return fail()
		}
	}
	if _, err = dec.Token(); err != nil || len(required) != 0 {
		return fail()
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return fail()
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(out) != nil {
		return fail()
	}
	return true
}
func (s *Server) initRuntimeIdentities() error {
	var err error
	s.runtimeIdentities, err = runtimeidentity.Open(s.d.Store.Dir, s.d.Key, s.intents, func(id string) error { _, e := s.resolveAdapterOptions(adapterinstall.Hermes, id); return e })
	return err
}
func runtimeIdentityError(w http.ResponseWriter, err error) {
	status := 503
	code := "runtime_identity_unavailable"
	switch {
	case errors.Is(err, runtimeidentity.ErrNoTools):
		status, code = 400, "runtime_identity_no_tools"
	case errors.Is(err, runtimeidentity.ErrInvalid):
		status = 400
		code = "runtime_identity_invalid_request"
	case errors.Is(err, runtimeidentity.ErrConflict), strings.HasPrefix(err.Error(), "intent_grant_"):
		status = 409
		code = "runtime_identity_authority_conflict"
	}
	writeJSON(w, status, map[string]string{"error": code})
}
func (s *Server) runtimeIdentityCollection(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	switch r.Method {
	case http.MethodGet:
		items, err := s.runtimeIdentities.List()
		if err != nil {
			runtimeIdentityError(w, err)
			return
		}
		writeJSON(w, 200, map[string]any{"schema_version": "local-runtime-identities/v1", "items": items})
	case http.MethodPost:
		var req runtimeidentity.CreateRequest
		if !readRuntimeIdentity(w, r, &req, "schema_version", "instance_id", "grant_id", "expected_grant_revision", "actor_id", "session_ttl_seconds") {
			return
		}
		record, err := s.runtimeIdentities.Create(req)
		if err != nil {
			runtimeIdentityError(w, err)
			return
		}
		summary, err := s.runtimeIdentities.Summary(record.IdentityID)
		if err != nil {
			runtimeIdentityError(w, err)
			return
		}
		path, err := s.runtimeIdentities.CredentialPath(record.IdentityID)
		if err != nil {
			runtimeIdentityError(w, err)
			return
		}
		writeJSON(w, 201, map[string]any{"schema_version": "local-runtime-identity-issued/v1", "identity": summary, "credential_path": path})
	default:
		w.WriteHeader(405)
	}
}
func (s *Server) runtimeIdentityOne(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	id := strings.TrimPrefix(r.URL.Path, "/v1/runtime-identities/")
	if !strings.HasSuffix(id, "/revoke") {
		w.WriteHeader(404)
		return
	}
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	id = strings.TrimSuffix(id, "/revoke")
	var req struct {
		SchemaVersion string `json:"schema_version"`
		ActorID       string `json:"actor_id"`
	}
	if !readRuntimeIdentity(w, r, &req, "schema_version", "actor_id") {
		return
	}
	if req.SchemaVersion != "local-runtime-identity-revoke/v1" {
		runtimeIdentityError(w, runtimeidentity.ErrInvalid)
		return
	}
	_, err := s.runtimeIdentities.Revoke(id, req.ActorID)
	if err != nil {
		runtimeIdentityError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"schema_version": "local-runtime-identity-revoked/v1", "identity_id": id, "revoked": true})
}
func (s *Server) runtimeSessionEnroll(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	if !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") {
		writeJSON(w, 401, map[string]string{"error": "runtime_identity_required"})
		return
	}
	credential := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	record, err := s.runtimeIdentities.Authenticate(credential)
	if err != nil {
		writeJSON(w, 401, map[string]string{"error": "runtime_identity_required"})
		return
	}
	var req runtimeidentity.EnrollRequest
	if !readRuntimeIdentity(w, r, &req, "schema_version", "session_id") {
		return
	}
	if req.SchemaVersion != "local-runtime-session-enroll/v1" {
		runtimeIdentityError(w, runtimeidentity.ErrInvalid)
		return
	}
	b, err := s.runtimeIdentities.Enroll(credential, req.SessionID)
	if err != nil {
		runtimeIdentityError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"schema_version": "local-runtime-session-enrolled/v1", "identity_id": record.IdentityID, "platform": record.Platform, "agent_id": record.AgentID, "session_id": req.SessionID, "binding_id": b.BindingID, "intent_id": b.IntentID, "expires_at": b.ExpiresAt})
}
