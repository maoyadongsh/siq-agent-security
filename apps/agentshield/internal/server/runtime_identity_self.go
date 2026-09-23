package server

import (
	"errors"
	"io"
	"net/http"
	"strings"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// These host-only routes are deliberately absent from the sandbox relay.
func (s *Server) runtimeIdentitySelf(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.URL.RawQuery != "" || r.URL.ForceQuery || r.URL.RawPath != "" {
		writeJSON(w, 400, map[string]string{"error": "runtime_identity_self_invalid_request"})
		return
	}
	revoke := r.URL.Path == "/v1/runtime-identity/self/revoke"
	if (revoke && r.Method != http.MethodPost) || (!revoke && r.Method != http.MethodGet) {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	headers := r.Header.Values("Authorization")
	if len(headers) != 1 || !strings.HasPrefix(headers[0], "Bearer ") {
		writeJSON(w, 401, map[string]string{"error": "runtime_identity_required"})
		return
	}
	credential := strings.TrimPrefix(headers[0], "Bearer ")
	if revoke {
		var req struct {
			SchemaVersion string `json:"schema_version"`
		}
		if !readRuntimeIdentity(w, r, &req, "schema_version") {
			return
		}
		if req.SchemaVersion != "local-runtime-identity-self-revoke/v1" {
			writeJSON(w, 400, map[string]string{"error": "runtime_identity_self_invalid_request"})
			return
		}
	} else if r.Body != nil {
		raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 0))
		if err != nil || len(raw) != 0 {
			writeJSON(w, 400, map[string]string{"error": "runtime_identity_self_invalid_request"})
			return
		}
	}
	if !runtimeIdentityResponseReady(w, r) {
		return
	}
	if !revoke {
		view, err := s.runtimeIdentities.Self(credential)
		if err != nil {
			writeJSON(w, 401, map[string]string{"error": "runtime_identity_required"})
			return
		}
		writeJSON(w, 200, view)
		return
	}
	rev, err := s.runtimeIdentities.RevokeSelf(credential)
	if errors.Is(err, runtimeidentity.ErrCredential) {
		writeJSON(w, 401, map[string]string{"error": "runtime_identity_required"})
		return
	}
	if err != nil {
		writeJSON(w, 503, map[string]string{"error": "runtime_identity_self_revoke_unconfirmed"})
		return
	}
	writeJSON(w, 200, map[string]any{"schema_version": "local-runtime-identity-revoked/v1", "identity_id": rev.IdentityID, "revoked": true})
}
