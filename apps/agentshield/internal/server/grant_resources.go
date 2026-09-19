package server

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

type grantResourceEdit struct {
	ConfirmFilesystemProfile *bool  `json:"confirm_filesystem_profile,omitempty"`
	SchemaVersion            string `json:"schema_version"`
	ExpectedRevision         *int   `json:"expected_revision"`
	ActorID                  string `json:"actor_id"`
	grant.ResourceEdit
}

func (s *Server) editGrantResources(w http.ResponseWriter, r *http.Request, g grant.Grant, seq int) {
	var body grantResourceEdit
	raw, readErr := io.ReadAll(http.MaxBytesReader(w, r.Body, 64<<10))
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()
	var extra any
	if readErr != nil || !uniqueJSONValue(raw) || decoder.Decode(&body) != nil || decoder.Decode(&extra) != io.EOF || (body.SchemaVersion != "grant-resource-edit/v1" && body.SchemaVersion != "grant-resource-edit/v2") || body.ExpectedRevision == nil || *body.ExpectedRevision < 0 || strings.TrimSpace(body.ActorID) == "" || utf8.RuneCountInString(body.ActorID) > 128 {
		writeJSON(w, 400, map[string]string{"error": "grant_resources_invalid"})
		return
	}
	if *body.ExpectedRevision != seq {
		writeJSON(w, 409, map[string]string{"error": "revision conflict"})
		return
	}
	if body.SchemaVersion == "grant-resource-edit/v2" && !exactWindowsResourceEdit(raw) {
		writeJSON(w, 400, map[string]string{"error": "grant_resources_invalid"})
		return
	}
	if body.SchemaVersion == "grant-resource-edit/v2" && stateformat.RequireWindowsProfile(s.d.Store.Dir) != nil {
		writeJSON(w, 409, map[string]string{"error": "windows_profile_activation_required"})
		return
	}
	if body.SchemaVersion == "grant-resource-edit/v1" && (body.ConfirmFilesystemProfile != nil || g.SchemaVersion != "") || body.SchemaVersion == "grant-resource-edit/v2" && (body.ConfirmFilesystemProfile == nil || !*body.ConfirmFilesystemProfile) {
		writeJSON(w, 400, map[string]string{"error": "grant_filesystem_profile_confirmation_required"})
		return
	}
	var out grant.Grant
	var policy grant.DesiredPolicy
	var err error
	if body.SchemaVersion == "grant-resource-edit/v2" && g.SchemaVersion == "" {
		out, policy, err = grant.PrepareWindowsResources(g, body.ResourceEdit, true, s.d.Key)
	} else {
		out, policy, err = grant.EditResources(g, body.ResourceEdit, s.d.Key)
	}
	if err != nil {
		status := 409
		if errors.Is(err, grant.ErrResourcesInvalid) {
			status = 400
		}
		writeJSON(w, status, map[string]string{"error": err.Error()})
		return
	}
	revision, err := s.d.Store.CommitGrant(state.GrantCommit{Grant: out, DesiredPolicy: policy, ExpectedRevision: seq, Audit: &state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: "grant_resources", ActorID: body.ActorID, Target: g.GrantID}})
	if err != nil {
		writeCommitError(w, err)
		return
	}
	s.invalidateProjection("grant_resources")
	writeJSON(w, 200, map[string]any{"grant": out, "state_revision": revision})
}

func exactWindowsResourceEdit(raw []byte) bool {
	if !exactJSONObject(raw, "schema_version", "expected_revision", "actor_id", "tools", "network", "filesystem", "models", "confirm_filesystem_profile") {
		return false
	}
	var fields struct {
		Filesystem json.RawMessage   `json:"filesystem"`
		Network    []json.RawMessage `json:"network"`
	}
	if json.Unmarshal(raw, &fields) != nil || !exactJSONObject(fields.Filesystem, "read_only", "read_write") {
		return false
	}
	for _, endpoint := range fields.Network {
		if !exactJSONObject(endpoint, "endpoint", "effect") {
			return false
		}
	}
	return true
}
