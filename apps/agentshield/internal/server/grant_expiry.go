package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

type grantExpiryEdit struct {
	SchemaVersion    string          `json:"schema_version"`
	ExpectedRevision *int            `json:"expected_revision"`
	ActorID          string          `json:"actor_id"`
	DurationSeconds  json.RawMessage `json:"duration_seconds"`
}

func (s *Server) editGrantExpiry(w http.ResponseWriter, r *http.Request, g grant.Grant, seq int) {
	var body grantExpiryEdit
	if readJSONStrict(r, &body, 16<<10) != nil || body.SchemaVersion != "grant-expiry-edit/v1" || body.ExpectedRevision == nil || *body.ExpectedRevision < 0 || strings.TrimSpace(body.ActorID) == "" || utf8.RuneCountInString(body.ActorID) > 128 || len(body.DurationSeconds) == 0 {
		writeJSON(w, 400, map[string]string{"error": "invalid grant expiration request"})
		return
	}
	var deadline *time.Time
	now := time.Now().UTC()
	if !bytes.Equal(bytes.TrimSpace(body.DurationSeconds), []byte("null")) {
		var seconds int64
		if json.Unmarshal(body.DurationSeconds, &seconds) != nil || seconds < 60 || seconds > 2592000 {
			writeJSON(w, 400, map[string]string{"error": "invalid grant duration"})
			return
		}
		at := now.Add(time.Duration(seconds) * time.Second)
		deadline = &at
	}
	if *body.ExpectedRevision != seq {
		writeJSON(w, 409, map[string]string{"error": "revision conflict"})
		return
	}
	out, err := grant.SetExpiration(g, deadline, now, s.d.Key)
	if err != nil {
		writeJSON(w, 400, map[string]string{"error": err.Error()})
		return
	}
	newSeq, err := s.d.Store.CommitGrant(state.GrantCommit{Grant: out, ExpectedRevision: seq,
		Audit: &state.AuditEvent{At: now.Format(time.RFC3339Nano), Event: "grant_expiry", Target: g.GrantID, ActorID: body.ActorID}})
	if err != nil {
		writeCommitError(w, err)
		return
	}
	s.invalidateProjection("grant_expiry")
	writeJSON(w, 200, map[string]any{"grant": out, "state_revision": newSeq})
}
