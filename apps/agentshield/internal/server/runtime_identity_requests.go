package server

import (
	"errors"
	"net/http"
	"strings"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

func runtimeRequestPost(w http.ResponseWriter, r *http.Request) bool {
	w.Header().Set("Cache-Control", "no-store")
	if r.URL.RawQuery != "" || r.URL.ForceQuery || r.URL.RawPath != "" {
		writeJSON(w, 400, map[string]string{"error": "runtime_identity_invalid_request"})
		return false
	}
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return false
	}
	return true
}

// Capability setup requires the existing local management boundary. It neither
// approves Grant nor installs an execution credential into a sandbox.
func (s *Server) runtimeRequestIssuer(w http.ResponseWriter, r *http.Request) {
	if !runtimeRequestPost(w, r) {
		return
	}
	var req runtimeidentity.RequestIssuerCreate
	if !readRuntimeIdentity(w, r, &req, "schema_version", "parent_identity_id", "scope_id", "max_identity_seconds", "expires_at", "actor_id") || !runtimeIdentityResponseReady(w, r) {
		return
	}
	v, err := s.runtimeIdentities.EnableRequestIssuer(req)
	if err != nil {
		runtimeIdentityError(w, err)
		return
	}
	v.Signature = ""
	writeJSON(w, http.StatusCreated, v)
}

// Host-only: these routes are not in the sandbox relay's closed allowlist.
func (s *Server) runtimeRequestIdentity(w http.ResponseWriter, r *http.Request) {
	if !runtimeRequestPost(w, r) {
		return
	}
	headers := r.Header.Values("Authorization")
	if len(headers) != 1 || !strings.HasPrefix(headers[0], "Bearer ") {
		writeJSON(w, 401, map[string]string{"error": "runtime_identity_required"})
		return
	}
	token := strings.TrimPrefix(headers[0], "Bearer ")
	if r.URL.Path == "/v1/runtime-identity/self/requests/cancel" {
		var req runtimeidentity.RequestIdentityCancel
		if !readRuntimeIdentity(w, r, &req, "schema_version", "request_id", "execution_sha256") || !runtimeIdentityResponseReady(w, r) {
			return
		}
		id, issued, err := s.runtimeIdentities.CancelRequest(token, req)
		if requestIdentityError(w, err) {
			return
		}
		writeJSON(w, 200, map[string]any{"schema_version": "local-runtime-request-identity-cancelled/v1", "identity_id": id, "cancelled": true, "issued": issued})
		return
	}
	var req runtimeidentity.RequestIdentityCreate
	if !readRuntimeIdentity(w, r, &req, "schema_version", "request_id", "execution_sha256", "expires_at") || !runtimeIdentityResponseReady(w, r) {
		return
	}
	record, err := s.runtimeIdentities.IssueRequest(token, req)
	if requestIdentityError(w, err) {
		return
	}
	summary, err := s.runtimeIdentities.Summary(record.IdentityID)
	if requestIdentityError(w, err) {
		return
	}
	path, err := s.runtimeIdentities.CredentialPath(record.IdentityID)
	if requestIdentityError(w, err) {
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"schema_version": "local-runtime-request-identity-issued/v1", "identity": summary, "request": record.RequestScope, "credential_path": path})
}
func requestIdentityError(w http.ResponseWriter, err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, runtimeidentity.ErrCredential) {
		writeJSON(w, 401, map[string]string{"error": "runtime_identity_required"})
	} else {
		runtimeIdentityError(w, err)
	}
	return true
}
