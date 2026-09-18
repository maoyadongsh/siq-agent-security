package server

import (
	"encoding/json"
	"io"
	"net/http"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

func readRuntimeIdentityCreate(w http.ResponseWriter, r *http.Request, out *runtimeidentity.CreateRequest) bool {
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 16<<10))
	var header struct {
		SchemaVersion string `json:"schema_version"`
	}
	fields := []string{"schema_version", "instance_id", "grant_id", "expected_grant_revision", "actor_id", "session_ttl_seconds"}
	if err == nil {
		err = json.Unmarshal(raw, &header)
	}
	if header.SchemaVersion == "local-runtime-identity-create/v2" {
		fields = append(fields, "confirm_filesystem_profile")
	}
	if err != nil || !exactJSONObject(raw, fields...) || json.Unmarshal(raw, out) != nil {
		writeJSON(w, 400, map[string]string{"error": "runtime_identity_invalid_request"})
		return false
	}
	return true
}
