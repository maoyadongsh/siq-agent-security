package skillcontext

import (
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	IssueRequestSchema  = "local-skill-execution-context-issue/v1"
	RevokeRequestSchema = "local-skill-execution-context-revoke/v1"
)

// ManagementIssueRequest is the strict admin API request. It intentionally
// cannot carry a platform, agent, Skill identity, Grant, or digest: Issue
// derives all authority from signed local state.
type ManagementIssueRequest struct {
	SchemaVersion string `json:"schema_version"`
	InstanceID    string `json:"instance_id"`
	SessionID     string `json:"session_id"`
	TaskID        string `json:"task_id"`
	InstallID     string `json:"install_id"`
	TTLSeconds    int    `json:"ttl_seconds"`
	ActorID       string `json:"actor_id"`
	ConfirmIssue  bool   `json:"confirm_issue"`
}

// ManagementRevokeRequest binds a confirmation to the exact immutable SEC
// the operator inspected. A copied or stale signature cannot revoke another
// context.
type ManagementRevokeRequest struct {
	SchemaVersion            string `json:"schema_version"`
	ExpectedContextSignature string `json:"expected_context_signature"`
	ActorID                  string `json:"actor_id"`
	ConfirmRevoke            bool   `json:"confirm_revoke"`
}

func validActor(value string) bool {
	return utf8.ValidString(value) && strings.TrimSpace(value) == value &&
		utf8.RuneCountInString(value) >= 1 && utf8.RuneCountInString(value) <= 128 &&
		strings.IndexFunc(value, unicode.IsControl) < 0
}

// Valid reports whether the request agrees with the JSON contract and the
// tighter Go text rules used by other local management APIs.
func (r ManagementIssueRequest) Valid() bool {
	return r.SchemaVersion == IssueRequestSchema && instancePattern.MatchString(r.InstanceID) &&
		textValid(r.SessionID, 256) && len(r.TaskID) <= 256 && utf8.ValidString(r.TaskID) &&
		textValid(r.InstallID, 128) && r.TTLSeconds >= 60 && r.TTLSeconds <= int(MaxTTL/time.Second) &&
		validActor(r.ActorID) && r.ConfirmIssue
}

// Valid reports whether the revocation request is exact and confirmed.
func (r ManagementRevokeRequest) Valid() bool {
	return r.SchemaVersion == RevokeRequestSchema && hex128Pattern.MatchString(r.ExpectedContextSignature) &&
		validActor(r.ActorID) && r.ConfirmRevoke
}
