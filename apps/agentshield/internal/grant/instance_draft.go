package grant

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/importsource"
)

var ErrInstanceDraft = errors.New("grant_instance_draft_invalid")
var instanceDraftRequestID = regexp.MustCompile(`^gid-[a-f0-9]{32}$`)
var instanceDraftAdmissionID = regexp.MustCompile(`^adm-[a-f0-9]{12}$`)
var instanceDraftSubjectID = regexp.MustCompile(`^hri-[a-f0-9]{32}$`)
var instanceDraftContentHash = regexp.MustCompile(`^[a-f0-9]{64}$`)

// InstanceDraftID scopes one idempotency key to its explicit human actor. The
// server must compare the persisted source/target before reusing this ID.
func InstanceDraftID(actor, request string) (string, error) {
	if actor == "" || !utf8.ValidString(actor) || strings.TrimSpace(actor) != actor || utf8.RuneCountInString(actor) > 128 || strings.IndexFunc(actor, unicode.IsControl) >= 0 || !instanceDraftRequestID.MatchString(request) {
		return "", ErrInstanceDraft
	}
	raw, err := canon.Marshal(map[string]any{"actor_id": actor, "request_id": request})
	if err != nil {
		return "", ErrInstanceDraft
	}
	digest := sha256.Sum256(raw)
	return "grt-id-" + hex.EncodeToString(digest[:]), nil
}

// BuildInstanceDraft creates a separate pending baseline before its first
// signature. It never accepts or modifies an existing signed Skill grant.
func BuildInstanceDraft(adm admission.Admission, opts Options, actor, request string) (*Result, error) {
	id, err := InstanceDraftID(actor, request)
	if err != nil || opts.Key == nil || !admission.Verify(opts.Key.Public(), adm) || importsource.Reserved(adm.AdmissionID) || !instanceDraftAdmissionID.MatchString(adm.AdmissionID) || !instanceDraftContentHash.MatchString(adm.ContentHash) || adm.AdmissionID != "adm-"+adm.ContentHash[:12] || adm.SkillID == "" || (adm.Verdict != "admit" && adm.Verdict != "admit_with_conditions") || opts.Subject.Type != "agent_instance" || !instanceDraftSubjectID.MatchString(opts.Subject.ID) || (opts.Platform != "hermes" && opts.Platform != "openclaw" && opts.Platform != "workbuddy") || opts.Scenario != nil {
		return nil, ErrInstanceDraft
	}
	opts.instanceGrantID = id
	return buildGrant(adm, opts)
}
