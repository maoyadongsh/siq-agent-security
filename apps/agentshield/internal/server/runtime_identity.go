package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// All fields in these flat request contracts are required, exact-case, non-null.
func readRuntimeIdentity(w http.ResponseWriter, r *http.Request, out any, fields ...string) bool {
	return readStrictFlatRequest(w, r, out, "runtime_identity_invalid_request", fields...)
}
func readStrictFlatRequest(w http.ResponseWriter, r *http.Request, out any, errorCode string, fields ...string) bool {
	return readStrictRequestLimit(w, r, out, errorCode, 16<<10, fields...)
}

func uniqueJSONValue(raw []byte) bool {
	dec := json.NewDecoder(bytes.NewReader(raw))
	var walk func() bool
	walk = func() bool {
		token, err := dec.Token()
		if err != nil {
			return false
		}
		delim, compound := token.(json.Delim)
		if !compound {
			return true
		}
		switch delim {
		case '{':
			seen := map[string]bool{}
			for dec.More() {
				key, err := dec.Token()
				name, ok := key.(string)
				if err != nil || !ok || seen[name] {
					return false
				}
				seen[name] = true
				if !walk() {
					return false
				}
			}
			end, err := dec.Token()
			return err == nil && end == json.Delim('}')
		case '[':
			for dec.More() {
				if !walk() {
					return false
				}
			}
			end, err := dec.Token()
			return err == nil && end == json.Delim(']')
		default:
			return false
		}
	}
	if !walk() {
		return false
	}
	var extra any
	return dec.Decode(&extra) == io.EOF
}

func exactJSONObject(raw []byte, fields ...string) bool {
	dec := json.NewDecoder(bytes.NewReader(raw))
	first, err := dec.Token()
	if err != nil || first != json.Delim('{') {
		return false
	}
	required := make(map[string]bool, len(fields))
	for _, field := range fields {
		required[field] = true
	}
	for dec.More() {
		key, err := dec.Token()
		name, ok := key.(string)
		if err != nil || !ok || !required[name] {
			return false
		}
		delete(required, name)
		var value json.RawMessage
		if dec.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) || !uniqueJSONValue(value) {
			return false
		}
	}
	if end, err := dec.Token(); err != nil || end != json.Delim('}') || len(required) != 0 {
		return false
	}
	var extra any
	return dec.Decode(&extra) == io.EOF
}

func readStrictRequestLimit(w http.ResponseWriter, r *http.Request, out any, errorCode string, limit int64, fields ...string) bool {
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, limit))
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
		if dec.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) || !uniqueJSONValue(value) {
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
	s.runtimeIdentities, err = runtimeidentity.OpenWithInstances(s.d.Store.Dir, s.d.Key, s.intents, func(id string) (runtimeidentity.InstanceInfo, error) {
		target, resolveErr := s.resolveRuntimeIdentityTarget(context.Background(), id)
		if resolveErr != nil {
			return runtimeidentity.InstanceInfo{}, resolveErr
		}
		return runtimeidentity.InstanceInfo{Platform: target.Platform, Root: target.Root}, nil
	})
	return err
}
func runtimeIdentityError(w http.ResponseWriter, err error) {
	status := 503
	code := "runtime_identity_unavailable"
	switch {
	case errors.Is(err, runtimeidentity.ErrProfileState):
		status, code = 409, "windows_profile_activation_required"
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
		version := "local-runtime-identities/v1"
		for _, item := range items {
			if item.FilesystemProfile != "" {
				version = "local-runtime-identities/v2"
			}
		}
		writeJSON(w, 200, map[string]any{"schema_version": version, "items": items})
	case http.MethodPost:
		var req runtimeidentity.CreateRequest
		if !readRuntimeIdentityCreate(w, r, &req) {
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
		version := "local-runtime-identity-issued/v1"
		if record.SchemaVersion == "local-runtime-identity/v2" {
			version = "local-runtime-identity-issued/v2"
		}
		writeJSON(w, 201, map[string]any{"schema_version": version, "identity": summary, "credential_path": path})
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
	var req runtimeidentity.EnrollRequest
	if !readRuntimeIdentity(w, r, &req, "schema_version", "session_id") {
		return
	}
	if req.SchemaVersion != "local-runtime-session-enroll/v1" {
		runtimeIdentityError(w, runtimeidentity.ErrInvalid)
		return
	}
	record, b, err := s.runtimeIdentities.EnrollContext(credential, req.SessionID)
	if err != nil {
		if errors.Is(err, runtimeidentity.ErrCredential) {
			writeJSON(w, 401, map[string]string{"error": "runtime_identity_required"})
			return
		}
		runtimeIdentityError(w, err)
		return
	}
	version := "local-runtime-session-enrolled/v1"
	if record.Platform == "workbuddy" {
		version = "local-runtime-session-enrolled/v2"
	}
	writeJSON(w, 200, map[string]any{"schema_version": version, "identity_id": record.IdentityID, "platform": record.Platform, "agent_id": record.AgentID, "session_id": req.SessionID, "binding_id": b.BindingID, "intent_id": b.IntentID, "expires_at": b.ExpiresAt})
}
