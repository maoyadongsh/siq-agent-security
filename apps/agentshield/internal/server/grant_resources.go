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
)

type grantResourceEdit struct {
	SchemaVersion    string `json:"schema_version"`
	ExpectedRevision *int   `json:"expected_revision"`
	ActorID          string `json:"actor_id"`
	grant.ResourceEdit
}

func (s *Server) editGrantResources(w http.ResponseWriter, r *http.Request, g grant.Grant, seq int) {
	var body grantResourceEdit
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10))
	decoder.DisallowUnknownFields()
	var extra any
	if decoder.Decode(&body) != nil || decoder.Decode(&extra) != io.EOF || body.SchemaVersion != "grant-resource-edit/v1" || body.ExpectedRevision == nil || *body.ExpectedRevision < 0 || strings.TrimSpace(body.ActorID) == "" || utf8.RuneCountInString(body.ActorID) > 128 {
		writeJSON(w, 400, map[string]string{"error": "grant_resources_invalid"})
		return
	}
	if *body.ExpectedRevision != seq {
		writeJSON(w, 409, map[string]string{"error": "revision conflict"})
		return
	}
	out, policy, err := grant.EditResources(g, body.ResourceEdit, s.d.Key)
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
